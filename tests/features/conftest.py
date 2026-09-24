import shutil
from pathlib import Path

import pandas as pd
import pytest

from the_bank_project.config import PROJECT_ROOT
from the_bank_project.gold import build_gold


@pytest.fixture
def repo(silver: dict[str, pd.DataFrame], tmp_path: Path) -> Path:
    """Cópia do repositório Feast sobre uma Gold sintética, no mesmo layout (`../data/gold`)."""
    gold_dir = tmp_path / "data" / "gold"
    gold_dir.mkdir(parents=True)
    for name, df in build_gold(silver).items():
        df.to_parquet(gold_dir / f"{name}.parquet", index=False)
    repo = tmp_path / "feature_repo"
    repo.mkdir()
    for name in ("feature_store.yaml", "features.py"):
        shutil.copy(PROJECT_ROOT / "feature_repo" / name, repo / name)
    return repo
