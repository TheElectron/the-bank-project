"""
    Raw (`.csv`) → Bronze (`.parquet`)
    Este módulo contém funções para converter arquivos `.csv` da camada Raw para arquivos `.parquet` na camada Bronze.
"""

import logging
import pandas as pd
from pathlib import Path
from the_bank_project.io import write_parquet_atomic

logger = logging.getLogger(__name__)

# Berka usa ';', padrão europeu
CSV_SEPARATOR = ";"


def csv_to_parquet(csv_path: Path, bronze_dir: Path, sep: str = CSV_SEPARATOR) -> Path:
    """
        Converte um `.csv` em `.parquet` sem alterar o dado.
        Tudo é lido como texto (`dtype=str`) e nada vira nulo automaticamente
        (`keep_default_na=False`), garantindo uma cópia exata.
    """
    df = pd.read_csv(csv_path, sep=sep, dtype=str, keep_default_na=False)
    target = write_parquet_atomic(df, bronze_dir / f"{csv_path.stem}.parquet")
    logger.info("%s -> %s (%d linhas, %d colunas)", csv_path.name, target.name, *df.shape)
    return target


def to_bronze(raw_dir: Path, bronze_dir: Path, sep: str = CSV_SEPARATOR) -> list[Path]:
    """
        Converte todos os arquivos `.csv` da Raw para `.parquet` na Bronze.
        Raises:
            FileNotFoundError: se a Raw não tiver nenhum `.csv`.
    """
    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"Nenhum .csv em {raw_dir}. Rode a ingestão para a Raw antes.")
    return [csv_to_parquet(path, bronze_dir, sep) for path in csv_files]
