import numpy as np
import pandas as pd
import pytest

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


@pytest.fixture(autouse=True)
def _isolated_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
