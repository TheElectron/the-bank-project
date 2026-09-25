import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from mlflow import MlflowClient

from the_bank_project.config import GlobalConfig, KaggleConfig, PathsConfig, SplitConfig, TrainingConfig
from the_bank_project.training.dataset import Dataset

N_MONTHS, N_ACCOUNTS = 24, 40


@pytest.fixture(scope="session")
def dataset() -> Dataset:  # imutável: os testes que alteram o alvo trabalham em cópias
    """Dataset sintético com sinal claro: o próximo outflow é ~ 0.8 x a média de 3 meses + ruído."""
    rng = np.random.default_rng(0)
    months = pd.date_range("1996-01-31", periods=N_MONTHS, freq="ME")
    base = rng.uniform(2_000, 20_000, N_ACCOUNTS)
    rows = []
    for m in months:
        avg3 = base * rng.uniform(0.8, 1.2, N_ACCOUNTS)
        rows.append(pd.DataFrame({
            "outflow_amount": base * rng.uniform(0.6, 1.4, N_ACCOUNTS), "outflow_3m_avg": avg3,
            "closing_balance": rng.uniform(0, 50_000, N_ACCOUNTS), "outflow_mom_change": rng.normal(0, 1, N_ACCOUNTS),
            "avg_transaction_amount": np.where(rng.random(N_ACCOUNTS) < 0.05, np.nan, rng.uniform(1, 30, N_ACCOUNTS)),
            "timestamp": m, "y": 0.8 * avg3 + rng.normal(0, 300, N_ACCOUNTS),
        }))  # fmt: skip
    df = pd.concat(rows, ignore_index=True).sort_values("timestamp", kind="stable", ignore_index=True)
    return Dataset(X=df.drop(columns=["timestamp", "y"]), y=df["y"], timestamps=df["timestamp"])


@pytest.fixture(scope="session")
def db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """SQLite do MLflow já migrado. Criar o schema custa ~45 s; copiar o arquivo, milissegundos."""
    path = tmp_path_factory.mktemp("mlflow_template") / "mlflow.db"
    MlflowClient(tracking_uri=f"sqlite:///{path}").search_experiments()
    return path


@pytest.fixture(scope="session")
def cfg_factory(db_template: Path) -> Callable[[Path], GlobalConfig]:
    """Config isolada: dados e MLflow (banco copiado do template) em `root`, poucos trials."""

    def make(root: Path) -> GlobalConfig:
        shutil.copy(db_template, root / "mlflow.db")
        training = TrainingConfig(
            n_tuning_trials=1, split=SplitConfig(train_frac=0.6, val_frac=0.2, gap_months=1),
            tracking_uri=f"sqlite:///{root / 'mlflow.db'}",
        )  # fmt: skip
        return GlobalConfig(paths=PathsConfig(data_dir=root), kaggle=KaggleConfig(dataset="o/d"), training=training)

    return make


@pytest.fixture
def cfg(tmp_path: Path, cfg_factory: Callable[[Path], GlobalConfig]) -> GlobalConfig:
    return cfg_factory(tmp_path)


@pytest.fixture(autouse=True)
def _isolated_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
