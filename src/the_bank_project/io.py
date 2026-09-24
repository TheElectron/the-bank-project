"""I/O compartilhado entre as camadas do data lake."""

from pathlib import Path

import pandas as pd


def write_parquet_atomic(df: pd.DataFrame, target: Path) -> Path:
    """Grava o parquet via arquivo temporário + `replace`, sem deixar arquivo parcial numa falha."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    df.to_parquet(tmp, engine="pyarrow", index=False)
    tmp.replace(target)
    return target
