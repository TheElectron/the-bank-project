#!/usr/bin/env python3
"""
raw_to_bronze.py
=================

Processa os dados brutos da camada `raw/` e alimenta a camada `bronze/`
do Datalake (arquitetura Medallion), convertendo cada `.csv` para
`.parquet` (pandas + pyarrow).

Este é um passo puramente de "landing"/formatação de armazenamento: nenhum
tratamento, limpeza, tipagem ou renomeação de coluna é aplicado aqui. A
Bronze deve ser uma cópia 1:1 da Raw, apenas em um formato colunar mais
eficiente (Parquet). Qualquer transformação de dado pertence às camadas
Silver/Gold.

--------------------------------------------------------------------------
PRÉ-REQUISITOS
--------------------------------------------------------------------------
1) Ambiente virtual ativo com as dependências instaladas:

     source .venv/bin/activate
     pip install -r requirements.txt

2) A camada `datalake/raw/` já populada (ver `datalake_setup.py`).

3) Executar:

     python src/scripts/raw_to_bronze.py

--------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# Configuração de logging (nível INFO conforme solicitado)
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("raw_to_bronze")

# --------------------------------------------------------------------------
# Constantes globais
# --------------------------------------------------------------------------
# O script vive em <raiz>/src/scripts/; subimos dois níveis para achar a
# raiz do projeto e, a partir dela, localizar o datalake/.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT / "datalake"

RAW_DIR = BASE_DIR / "raw"
BRONZE_DIR = BASE_DIR / "bronze"

# O dataset Berka usa ';' como delimitador (padrão de exportação europeu).
CSV_SEPARATOR = ";"


# --------------------------------------------------------------------------
# 1) Descoberta dos arquivos .csv na camada Raw
# --------------------------------------------------------------------------
def find_csv_files(raw_dir: Path) -> list[Path]:
    """Lista todos os arquivos `.csv` disponíveis na camada Raw.

    Args:
        raw_dir: diretório `datalake/raw/`.

    Returns:
        Lista ordenada de caminhos para os arquivos .csv encontrados
        (apenas no nível raiz de `raw_dir`, sem recursão em subpastas).

    Raises:
        FileNotFoundError: se o diretório não existir ou não contiver
            nenhum arquivo .csv.
    """
    if not raw_dir.is_dir():
        raise FileNotFoundError(
            f"Diretório da camada Raw não encontrado: {raw_dir}. "
            "Execute a ingestão inicial (datalake_setup.py) antes."
        )

    csv_files = sorted(p for p in raw_dir.glob("*.csv") if p.is_file())
    if not csv_files:
        raise FileNotFoundError(f"Nenhum arquivo .csv encontrado em {raw_dir}.")

    logger.info("Encontrados %d arquivo(s) .csv em %s.", len(csv_files), raw_dir)
    return csv_files


# --------------------------------------------------------------------------
# 2) Conversão individual: .csv (Raw) -> .parquet (Bronze)
# --------------------------------------------------------------------------
def convert_csv_to_parquet(csv_path: Path, bronze_dir: Path, sep: str = CSV_SEPARATOR) -> Path:
    """Converte um único `.csv` da Raw em `.parquet` na Bronze, sem alterar o dado.

    Regra de ouro: cópia 1:1. Para isso:
      - `dtype=str`: todas as colunas são lidas como texto, evitando que o
        pandas infira/coaja tipos (int, float, datetime, bool...).
      - `keep_default_na=False` e `na_filter=False`: desliga a detecção
        automática de "valores nulos" do pandas (que por padrão trataria
        strings como "NA", "NULL", "" etc. como NaN). Sem isso, mesmo com
        dtype=str, o conteúdo textual original poderia ser silenciosamente
        substituído por NaN — o que violaria a cópia exata exigida.
      - `index=False` na escrita: evita adicionar uma coluna de índice
        artificial que não existe no CSV original.

    Args:
        csv_path: caminho do arquivo .csv de origem (em datalake/raw/).
        bronze_dir: diretório de destino (datalake/bronze/).
        sep: delimitador do CSV (';' para o dataset Berka).

    Returns:
        Path do arquivo .parquet gerado.

    Raises:
        pd.errors.EmptyDataError: se o .csv estiver vazio (sem cabeçalho).
        pd.errors.ParserError: se o .csv estiver malformado.
        Exception: qualquer outra falha de leitura/escrita é relançada
            após ser registrada no log.
    """
    parquet_path = bronze_dir / f"{csv_path.stem}.parquet"

    try:
        df = pd.read_csv(
            csv_path,
            sep=sep,
            dtype=str,  # nenhuma coerção de tipo: tudo permanece string
            keep_default_na=False,  # não interpretar "NA"/"NULL"/etc. como nulo
            na_filter=False,  # não converter campos vazios em NaN
            engine="c",
        )
    except pd.errors.EmptyDataError:
        logger.exception("Arquivo .csv vazio (sem cabeçalho/dados): %s", csv_path.name)
        raise
    except pd.errors.ParserError:
        logger.exception("Falha ao parsear o .csv (verifique o delimitador '%s'): %s", sep, csv_path.name)
        raise
    except Exception:
        logger.exception("Falha inesperada ao ler o .csv: %s", csv_path.name)
        raise

    n_rows, n_cols = df.shape
    logger.info(
        "  - lido:    %-16s | linhas=%d | colunas=%d", csv_path.name, n_rows, n_cols
    )

    try:
        df.to_parquet(parquet_path, engine="pyarrow", index=False)
    except Exception:
        logger.exception("Falha ao gravar o .parquet: %s", parquet_path)
        raise

    logger.info("  - gravado: %-16s -> %s", csv_path.name, parquet_path.name)
    return parquet_path


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------
def run(raw_dir: Path = RAW_DIR, bronze_dir: Path = BRONZE_DIR, sep: str = CSV_SEPARATOR) -> None:
    """Executa o pipeline completo Raw -> Bronze para todos os .csv encontrados.

    Cada arquivo é processado de forma independente: uma falha em um
    arquivo é registrada no log, mas não interrompe o processamento dos
    demais. Ao final, se houver qualquer falha, uma exceção é levantada
    para sinalizar o erro ao chamador (código de saída != 0).

    Args:
        raw_dir: diretório de origem (datalake/raw/).
        bronze_dir: diretório de destino (datalake/bronze/).
        sep: delimitador usado nos .csv de origem.

    Raises:
        RuntimeError: se um ou mais arquivos falharem na conversão.
    """
    bronze_dir.mkdir(parents=True, exist_ok=True)

    csv_files = find_csv_files(raw_dir)

    succeeded: list[Path] = []
    failed: list[tuple[Path, Exception]] = []

    logger.info("Iniciando conversão Raw -> Bronze (%d arquivo(s))...", len(csv_files))
    for csv_path in csv_files:
        try:
            parquet_path = convert_csv_to_parquet(csv_path, bronze_dir, sep=sep)
            succeeded.append(parquet_path)
        except Exception as exc:  # noqa: BLE001 - captura ampla e intencional: isola falhas por arquivo
            failed.append((csv_path, exc))

    logger.info(
        "Conversão finalizada: %d sucesso(s), %d falha(s).", len(succeeded), len(failed)
    )

    if failed:
        nomes = ", ".join(p.name for p, _ in failed)
        raise RuntimeError(f"Falha ao converter {len(failed)} arquivo(s): {nomes}")

    logger.info("Camada Bronze atualizada com sucesso em: %s", bronze_dir)


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(
        description="Converte os .csv da camada Raw em .parquet na camada Bronze (cópia 1:1)."
    )
    parser.add_argument(
        "--raw-dir",
        default=str(RAW_DIR),
        help=f"Diretório de origem dos .csv (padrão: {RAW_DIR}).",
    )
    parser.add_argument(
        "--bronze-dir",
        default=str(BRONZE_DIR),
        help=f"Diretório de destino dos .parquet (padrão: {BRONZE_DIR}).",
    )
    parser.add_argument(
        "--sep",
        default=CSV_SEPARATOR,
        help=f"Delimitador dos .csv de origem (padrão: '{CSV_SEPARATOR}').",
    )
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    try:
        run(raw_dir=Path(args.raw_dir), bronze_dir=Path(args.bronze_dir), sep=args.sep)
    except Exception as exc:  # noqa: BLE001 - captura ampla e intencional no nível mais alto
        logger.error("Falha na execução do script: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
