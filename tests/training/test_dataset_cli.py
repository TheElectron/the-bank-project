from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from the_bank_project.features import apply_repo
from the_bank_project.gold import build_gold
from the_bank_project.training import cli
from the_bank_project.training.dataset import load_dataset
from the_bank_project.training.labels import LABELS_TABLE, TARGET, build_labels


def _write_labels(repo: Path, silver: dict[str, pd.DataFrame], extra: pd.DataFrame | None = None) -> Path:
    gold_dir = repo.parent / "data" / "gold"
    labels = build_labels(build_gold(silver)["gold_account_monthly_movements"])
    labels = pd.concat([labels, extra]) if extra is not None else labels
    labels.to_parquet(gold_dir / f"{LABELS_TABLE}.parquet", index=False)
    return gold_dir


def test_load_dataset_joins_labels_with_point_in_time_features(repo: Path, silver: dict[str, pd.DataFrame]):
    gold_dir = _write_labels(repo, silver)
    apply_repo(repo)
    ds = load_dataset(gold_dir, "outflow_regression", repo)
    assert ds.y.tolist() == [0.0, 200.0]  # conta 1: jan->fev = 0, fev->mar = 200 (a conta 2 só tem 1 mês)
    assert len(ds.X) == 2 and (ds.X.dtypes == np.float64).all() and "next_month_outflow" not in ds.X.columns
    assert ds.X["closing_balance"].tolist() == [700.0, 700.0]  # jan fechou em 700; fev não teve movimento
    assert ds.X["outflow_amount"].tolist() == [300.0, 0.0]  # features de T, não do mês do target
    assert ds.timestamps.tolist() == [pd.Timestamp("1993-01-31"), pd.Timestamp("1993-02-28")]


def test_load_dataset_fails_if_feast_drops_rows(repo: Path, silver: dict[str, pd.DataFrame]):
    orphan = pd.DataFrame({"account_id": ["2"], "event_timestamp": [pd.Timestamp("1993-01-31")], TARGET: [1.0]})
    gold_dir = _write_labels(repo, silver, orphan)  # a conta 2 só abre em fev/93
    apply_repo(repo)
    with pytest.raises(ValueError, match="não devolveu features"):
        load_dataset(gold_dir, "outflow_regression", repo)


def test_load_dataset_requires_labels(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="labels"):
        load_dataset(tmp_path, "outflow_regression")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    from the_bank_project.config import GlobalConfig, KaggleConfig, PathsConfig

    calls: list[str] = []
    cfg = GlobalConfig(paths=PathsConfig(data_dir=tmp_path), kaggle=KaggleConfig(dataset="o/d"))
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "gold_to_labels", lambda gold: calls.append("labels"))
    monkeypatch.setattr(cli, "run_training", lambda c: calls.append(f"train:{c.training.n_tuning_trials}"))
    monkeypatch.setattr(cli, "promote", lambda c: calls.append("promote"))
    return calls


@pytest.mark.parametrize(
    ("step", "expected"), [("labels", ["labels"]), ("train", ["train:8"]), ("promote", ["promote"])]
)
def test_cli_runs_requested_step(calls: list[str], step: str, expected: list[str]):
    assert cli.main([step]) == 0 and calls == expected


def test_cli_trials_option_overrides_config(calls: list[str]):
    assert cli.main(["train", "--trials", "2"]) == 0 and calls == ["train:2"]


def test_cli_returns_1_on_error(calls: list[str], monkeypatch: pytest.MonkeyPatch):
    def boom(*a: object) -> None:
        raise RuntimeError("falhou")

    monkeypatch.setattr(cli, "promote", boom)
    assert cli.main(["promote"]) == 1
