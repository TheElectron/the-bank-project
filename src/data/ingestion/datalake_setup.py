#!/usr/bin/env python3
"""Provisiona a estrutura local do Datalake (raw -> bronze -> silver) e baixa o
"The Berka Dataset" (Kaggle) para `datalake/raw/`. Setup e credenciais: ver
README, seção "Datalake Setup".
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path

from src.common import DATALAKE_DIR, configure_logging, run_cli

logger = configure_logging("datalake_setup")

DATASET_SLUG = "marceloventura/the-berka-dataset"

# Subpastas do escopo atual do datalake (raw -> bronze -> silver).
MEDALLION_DIRS = [DATALAKE_DIR / "raw", DATALAKE_DIR / "bronze", DATALAKE_DIR / "silver"]

# Pasta temporária de trabalho, removida ao final do download/extração.
TMP_DOWNLOAD_DIR = DATALAKE_DIR / "raw" / "_tmp_kaggle_download"


# 1) Estrutura de diretórios
def create_directory_structure(directories: list[Path]) -> None:
    """Cria (de forma idempotente) as pastas da arquitetura Medallion."""
    logger.info("Etapa 1/5: verificando/criando estrutura de diretórios do Datalake...")
    for directory in directories:
        already_existed = directory.exists()
        directory.mkdir(parents=True, exist_ok=True)
        logger.info("  - %s: %s", "já existia" if already_existed else "criado", directory)
    logger.info("Estrutura de diretórios pronta em: %s", DATALAKE_DIR)


# 2) Credenciais da Kaggle API
def ensure_kaggle_credentials() -> None:
    """Verifica se alguma credencial da Kaggle API está configurada.

    O pacote `kaggle` (>=2.x) tenta autenticar, nesta ordem: access token
    novo (env `KAGGLE_API_TOKEN`, ou `~/.kaggle/access_token[.txt]`),
    legacy API key (`~/.kaggle/kaggle.json` ou env
    `KAGGLE_USERNAME`/`KAGGLE_KEY`), ou OAuth interativo/anônimo. Como
    fallback específico deste projeto, também aceitamos um token em
    `<raiz>/kaggle/settings.json` (arquivo com só o valor do token, sem
    estrutura JSON) — se encontrado, é exposto via `KAGGLE_API_TOKEN`.

    Raises:
        FileNotFoundError: quando nenhuma credencial é encontrada.
    """
    logger.info("Etapa 2/5: validando credenciais da Kaggle API...")
    config_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))

    if os.environ.get("KAGGLE_API_TOKEN"):
        logger.info("  - credenciais (access token) via variável de ambiente KAGGLE_API_TOKEN.")
        return
    for filename in ("access_token", "access_token.txt"):
        token_file = config_dir / filename
        if token_file.is_file() and token_file.read_text(encoding="utf-8").strip():
            logger.info("  - credenciais (access token) em: %s", token_file)
            return
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        logger.info("  - credenciais (legacy api key) via variáveis de ambiente.")
        return
    kaggle_json = config_dir / "kaggle.json"
    if kaggle_json.is_file():
        logger.info("  - credenciais (legacy api key) em: %s", kaggle_json)
        return

    # Fallback específico deste projeto: token em <raiz>/kaggle/settings.json
    # (local não padrão da lib Kaggle).
    local_token_file = DATALAKE_DIR.parent / "kaggle" / "settings.json"
    if local_token_file.is_file() and local_token_file.read_text(encoding="utf-8").strip():
        os.environ["KAGGLE_API_TOKEN"] = str(local_token_file)
        logger.info("  - credenciais (access token) em local não padrão do projeto: %s", local_token_file)
        return

    raise FileNotFoundError(
        "Credenciais da Kaggle API não encontradas. Gere um token em "
        "https://www.kaggle.com/settings/api e salve-o em "
        f"'{config_dir / 'access_token'}' (chmod 600), defina a variável de "
        "ambiente KAGGLE_API_TOKEN, ou use o formato legacy "
        f"'{kaggle_json}' com username/key."
    )


# 3) Download do dataset
def download_dataset(dataset_slug: str, download_dir: Path) -> Path:
    """Baixa o dataset da Kaggle API (.zip) para `download_dir` e retorna o caminho.

    Importa `kaggle` dentro da função (não no topo do módulo): a lib
    tenta autenticar no momento do import, e `ensure_kaggle_credentials()`
    precisa rodar antes para produzir um erro amigável.

    Raises:
        RuntimeError: se o download falhar ou o .zip não for encontrado.
    """
    logger.info("Etapa 3/5: baixando dataset '%s' via Kaggle API...", dataset_slug)
    download_dir.mkdir(parents=True, exist_ok=True)

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as exc:
        raise RuntimeError("Biblioteca 'kaggle' não instalada. Rode 'poetry install'.") from exc

    api = KaggleApi()
    api.authenticate()
    api.dataset_download_files(dataset_slug, path=str(download_dir), unzip=False, quiet=False)

    zip_candidates = list(download_dir.glob("*.zip"))
    if not zip_candidates:
        raise RuntimeError(f"Download concluído mas nenhum arquivo .zip foi encontrado em {download_dir}.")
    logger.info("  - download concluído: %s", zip_candidates[0])
    return zip_candidates[0]


# 4) Extração
def extract_zip(zip_path: Path, extract_to: Path) -> Path:
    """Extrai `zip_path` para `extract_to` e retorna o diretório de destino."""
    logger.info("Etapa 4/5: extraindo arquivo '%s'...", zip_path.name)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)
        n_files = len(zf.namelist())
    logger.info("  - %d arquivo(s) extraído(s) para: %s", n_files, extract_to)
    return extract_to


# 5) Movimentação dos CSVs para raw/
def move_csv_files(source_dir: Path, raw_dir: Path) -> list[Path]:
    """Move (sem reescrever) os .csv de `source_dir` para `raw_dir`.

    `shutil.move` transfere os bytes originais sem abri-los para leitura/
    escrita, garantindo que o conteúdo fique absolutamente inalterado.

    Raises:
        FileNotFoundError: se nenhum .csv for encontrado em `source_dir`.
    """
    csv_files = sorted(source_dir.rglob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"Nenhum arquivo .csv encontrado em {source_dir}.")

    moved_files = []
    for csv_file in csv_files:
        destination = raw_dir / csv_file.name
        if destination.exists():
            logger.warning("  - arquivo já existe em raw/, será sobrescrito: %s", destination.name)
            destination.unlink()
        shutil.move(str(csv_file), str(destination))
        logger.info("  - movido: %s -> %s", csv_file.name, destination)
        moved_files.append(destination)
    return moved_files


# 6) Limpeza dos artefatos temporários
def cleanup(paths_to_remove: list[Path]) -> None:
    """Remove (best-effort) os arquivos/pastas temporários do download/extração."""
    logger.info("Etapa 5/5: limpando arquivos temporários...")
    for path in paths_to_remove:
        try:
            if path.is_dir():
                shutil.rmtree(path)
                logger.info("  - diretório removido: %s", path)
            elif path.is_file():
                path.unlink()
                logger.info("  - arquivo removido: %s", path)
        except OSError:
            logger.warning("  - não foi possível remover: %s", path, exc_info=True)


# Orquestração
def run(dataset_slug: str = DATASET_SLUG, base_dir: Path = DATALAKE_DIR) -> None:
    """Executa o pipeline completo: cria a estrutura de pastas e ingere o dataset em `raw/`."""
    raw_dir = base_dir / "raw"
    tmp_dir = raw_dir / "_tmp_kaggle_download"
    directories = [raw_dir, base_dir / "bronze", base_dir / "silver"]

    try:
        create_directory_structure(directories)
        ensure_kaggle_credentials()
        zip_path = download_dataset(dataset_slug, tmp_dir)
        extract_zip(zip_path, tmp_dir)
        move_csv_files(tmp_dir, raw_dir)
    except Exception:
        logger.exception("Pipeline de ingestão interrompido devido a um erro.")
        raise
    finally:
        # A limpeza roda mesmo se algo falhar após o download, para não
        # deixar lixo (zip / pasta temporária) no ambiente.
        cleanup([tmp_dir])

    logger.info("Ingestão inicial concluída com sucesso. Arquivos disponíveis em: %s", raw_dir)


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(
        description="Provisiona o Datalake local (Medallion) e ingere o dataset Berka via Kaggle API."
    )
    parser.add_argument("--dataset", default=DATASET_SLUG, help=f"Dataset da Kaggle (padrão: {DATASET_SLUG}).")
    parser.add_argument("--base-dir", default=str(DATALAKE_DIR), help=f"Diretório raiz do datalake (padrão: {DATALAKE_DIR}).")
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    return run_cli(lambda: run(dataset_slug=args.dataset, base_dir=Path(args.base_dir)), logger)


if __name__ == "__main__":
    sys.exit(main())
