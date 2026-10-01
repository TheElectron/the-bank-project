"""
    Kaggle → Raw (`.csv`)
    Este módulo contém funções para baixar e extrair datasets do Kaggle para a camada Raw. 
"""

import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from the_bank_project.config import Settings

logger = logging.getLogger(__name__)


def _export_kaggle_credentials(settings: Settings) -> None:
    """
        Expõe as credenciais do `.env` em `os.environ`, para leitura pela lib `kaggle`.
    """
    for name, value in {
        "KAGGLE_USERNAME": settings.kaggle_username,
        "KAGGLE_KEY": settings.kaggle_key,
        "KAGGLE_API_TOKEN": settings.kaggle_api_token,
    }.items():
        if value:
            os.environ.setdefault(name, value)


def download_dataset(dataset: str, dest_dir: Path) -> Path:
    """
        Baixa o dataset (.zip) do Kaggle para `dest_dir` e retorna o caminho do zip.
        Raises:
            RuntimeError: se o download terminar sem gerar arquivo `.zip`.
    """
    _export_kaggle_credentials(Settings())
    # A lib realiza a autenticação no import, e sem credenciais isso quebraria, por isso o import tardio.
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    api.dataset_download_files(dataset, path=str(dest_dir), unzip=False, quiet=True)
    zips = sorted(dest_dir.glob("*.zip"))
    if not zips:
        raise RuntimeError(f"Erro ao realizar o download de '{dataset}', arquivo não encontrado em {dest_dir}.")
    return zips[0]


def extract_csvs(zip_path: Path, raw_dir: Path) -> list[Path]:
    """
        Extrai os arquivos `.csv` contidos no arquivo `.zip` para `raw_dir`.
        Raises:
            FileNotFoundError: se o `.zip` não possuir nenhum arquivo `.csv`.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = Path(member.filename).name
            if member.is_dir() or not name.lower().endswith(".csv") or "__MACOSX" in member.filename:
                continue
            target = raw_dir / name
            tmp = target.with_name(f".{name}.tmp")
            with zf.open(member) as src, tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            tmp.replace(target)
            extracted.append(target)
    if not extracted:
        raise FileNotFoundError(f"Nenhum arquivo .csv encontrado em {zip_path}.")
    return sorted(extracted)


def download_to_raw(dataset: str, raw_dir: Path, force: bool = False) -> list[Path]:
    """
        Realiza o download e extração dos arquivos .csv do dataset para a camada Raw.
        Args:
            dataset: slug do dataset no Kaggle (`dono/nome`).
            raw_dir: pasta de destino na camada Raw.
            force: sobrescreve os arquivos na pasta de destino.

        Returns:
            Paths dos `.csv` na Raw, em ordem alfabética.
    """
    existing = sorted(raw_dir.glob("*.csv"))
    if existing and not force:
        logger.info("Raw já populada (%d .csv em %s); pulando download.", len(existing), raw_dir)
        return existing
    logger.info("Baixando '%s' do Kaggle...", dataset)
    with tempfile.TemporaryDirectory(prefix="kaggle_") as tmp:
        zip_path = download_dataset(dataset, Path(tmp))
        files = extract_csvs(zip_path, raw_dir)
    logger.info("%d arquivo(s) gravado(s) em %s: %s", len(files), raw_dir, ", ".join(f.name for f in files))
    return files
