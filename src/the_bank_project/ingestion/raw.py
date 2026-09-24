"""Kaggle → Raw: baixa o dataset e guarda os `.csv` originais, sem alteração."""

import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from the_bank_project.config import Settings

logger = logging.getLogger(__name__)


def _export_kaggle_credentials(settings: Settings) -> None:
    """Expõe as credenciais do `.env` em `os.environ`, que é o que a lib `kaggle` lê.

    Não sobrescreve variáveis já definidas no ambiente.
    """
    for name, value in {
        "KAGGLE_USERNAME": settings.kaggle_username,
        "KAGGLE_KEY": settings.kaggle_key,
        "KAGGLE_API_TOKEN": settings.kaggle_api_token,
    }.items():
        if value:
            os.environ.setdefault(name, value)


def download_dataset(dataset: str, dest_dir: Path) -> Path:
    """Baixa o dataset (.zip) do Kaggle para `dest_dir` e retorna o caminho do zip.

    Raises:
        RuntimeError: se o download terminar sem gerar um `.zip`.
    """
    _export_kaggle_credentials(Settings())
    # Import tardio: a lib autentica já no import, e sem credenciais isso
    # quebraria até o import deste módulo (e os testes).
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    api.dataset_download_files(dataset, path=str(dest_dir), unzip=False, quiet=True)
    zips = sorted(dest_dir.glob("*.zip"))
    if not zips:
        raise RuntimeError(f"Download de '{dataset}' concluído, mas nenhum .zip em {dest_dir}.")
    return zips[0]


def extract_csvs(zip_path: Path, raw_dir: Path) -> list[Path]:
    """Extrai só os `.csv` do zip para `raw_dir`, em estrutura plana.

    Usa apenas o nome base de cada membro (protege contra path traversal) e
    grava via arquivo temporário + `replace`, então reexecutar sobrescreve
    sem deixar arquivo parcial.

    Raises:
        FileNotFoundError: se o zip não contiver nenhum `.csv`.
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
    """Garante os `.csv` originais do dataset em `raw_dir`.

    Idempotente: se já houver `.csv` na Raw, não baixa de novo (use `force=True`
    para refazer o download).

    Args:
        dataset: slug do dataset no Kaggle (`dono/nome`).
        raw_dir: pasta de destino da camada Raw.
        force: baixa e sobrescreve mesmo que a Raw já esteja populada.

    Returns:
        Caminhos dos `.csv` na Raw, em ordem alfabética.
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
