"""Raw → Bronze: `.csv` → `.parquet`, cópia 1:1 (sem tipagem nem tratamento — isso é da Silver)."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# O Berka usa ';' como delimitador (exportação europeia).
CSV_SEPARATOR = ";"


def csv_to_parquet(csv_path: Path, bronze_dir: Path, sep: str = CSV_SEPARATOR) -> Path:
    """Converte um `.csv` em `.parquet` sem alterar o dado.

    Tudo é lido como texto (`dtype=str`) e nada vira nulo automaticamente
    (`keep_default_na=False`), senão o pandas inferiria tipos e trocaria
    `""`/`"NA"` por `NaN`, violando a cópia exata. A escrita passa por arquivo
    temporário + `replace`, então uma falha no meio não deixa parquet corrompido.
    """
    bronze_dir.mkdir(parents=True, exist_ok=True)
    target = bronze_dir / f"{csv_path.stem}.parquet"
    tmp = target.with_name(f".{target.name}.tmp")
    df = pd.read_csv(csv_path, sep=sep, dtype=str, keep_default_na=False)
    df.to_parquet(tmp, engine="pyarrow", index=False)
    tmp.replace(target)
    logger.info("%s -> %s (%d linhas, %d colunas)", csv_path.name, target.name, *df.shape)
    return target


def to_bronze(raw_dir: Path, bronze_dir: Path, sep: str = CSV_SEPARATOR) -> list[Path]:
    """Converte todos os `.csv` da Raw para `.parquet` na Bronze.

    Raises:
        FileNotFoundError: se a Raw não tiver nenhum `.csv`.
    """
    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"Nenhum .csv em {raw_dir}. Rode a ingestão para a Raw antes.")
    return [csv_to_parquet(path, bronze_dir, sep) for path in csv_files]
