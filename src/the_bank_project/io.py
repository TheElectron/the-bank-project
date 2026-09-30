"""I/O compartilhado entre as camadas do data lake."""


import pandas as pd
from pathlib import Path


def write_parquet_atomic(df: pd.DataFrame, target: Path) -> Path:
    """
        Método responsável pela escrita atômicado arquivo `.parquet`.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    df.to_parquet(tmp, engine="pyarrow", index=False)
    tmp.replace(target)
    return target
