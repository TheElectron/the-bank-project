#!/usr/bin/env python3
"""Converte cada `.csv` da camada `raw/` em `.parquet` na `bronze/` (pandas +
pyarrow). Passo puramente de formatação de armazenamento — cópia 1:1 da Raw,
sem tratamento/tipagem (isso pertence à Silver).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from src.common import DATALAKE_DIR, configure_logging, run_cli

logger = configure_logging("raw_to_bronze")

RAW_DIR = DATALAKE_DIR / "raw"
BRONZE_DIR = DATALAKE_DIR / "bronze"

# O dataset Berka usa ';' como delimitador (padrão de exportação europeu).
CSV_SEPARATOR = ";"


def find_csv_files(raw_dir: Path) -> list[Path]:
    """Lista os arquivos `.csv` da camada Raw, em ordem.

    Raises:
        FileNotFoundError: se o diretório não existir ou estiver vazio.
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


def convert_csv_to_parquet(csv_path: Path, bronze_dir: Path, sep: str = CSV_SEPARATOR) -> Path:
    """Converte um `.csv` da Raw em `.parquet` na Bronze, sem alterar o dado.

    Cópia 1:1: `dtype=str` evita que o pandas infira tipos, e
    `keep_default_na=False`/`na_filter=False` desligam a detecção
    automática de nulo (senão strings como `""` virariam `NaN`
    silenciosamente, violando a cópia exata exigida pela Bronze).
    """
    parquet_path = bronze_dir / f"{csv_path.stem}.parquet"
    df = pd.read_csv(csv_path, sep=sep, dtype=str, keep_default_na=False, na_filter=False, engine="c")
    logger.info("  - lido:    %-16s | linhas=%d | colunas=%d", csv_path.name, *df.shape)
    df.to_parquet(parquet_path, engine="pyarrow", index=False)
    logger.info("  - gravado: %-16s -> %s", csv_path.name, parquet_path.name)
    return parquet_path


def run(raw_dir: Path = RAW_DIR, bronze_dir: Path = BRONZE_DIR, sep: str = CSV_SEPARATOR) -> None:
    """Converte todos os `.csv` da Raw para a Bronze.

    Cada arquivo é processado de forma independente: uma falha é
    registrada mas não interrompe os demais; ao final, se houve alguma
    falha, uma exceção é levantada para sinalizar o erro ao chamador.

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
            succeeded.append(convert_csv_to_parquet(csv_path, bronze_dir, sep=sep))
        except Exception as exc:  # noqa: BLE001 - captura ampla e intencional: isola falhas por arquivo
            logger.exception("Falha ao converter '%s'.", csv_path.name)
            failed.append((csv_path, exc))

    logger.info("Conversão finalizada: %d sucesso(s), %d falha(s).", len(succeeded), len(failed))
    if failed:
        nomes = ", ".join(p.name for p, _ in failed)
        raise RuntimeError(f"Falha ao converter {len(failed)} arquivo(s): {nomes}")
    logger.info("Camada Bronze atualizada com sucesso em: %s", bronze_dir)


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(description="Converte os .csv da Raw em .parquet na Bronze (cópia 1:1).")
    parser.add_argument("--raw-dir", default=str(RAW_DIR), help=f"Padrão: {RAW_DIR}.")
    parser.add_argument("--bronze-dir", default=str(BRONZE_DIR), help=f"Padrão: {BRONZE_DIR}.")
    parser.add_argument("--sep", default=CSV_SEPARATOR, help=f"Delimitador dos .csv de origem (padrão: '{CSV_SEPARATOR}').")
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    return run_cli(lambda: run(Path(args.raw_dir), Path(args.bronze_dir), args.sep), logger)


if __name__ == "__main__":
    sys.exit(main())
