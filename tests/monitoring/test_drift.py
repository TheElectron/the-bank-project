"""Drift de dados com dados sintéticos: injetado é detectado, ausente não dispara nada."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from the_bank_project.config import GlobalConfig, KaggleConfig, MonitoringConfig, PathsConfig
from the_bank_project.monitoring import compute_drift, run_drift, select_windows
from the_bank_project.monitoring.cli import main
from the_bank_project.training.dataset import Dataset
from the_bank_project.training.split import chronological_split

N_MONTHS, N_ACCOUNTS = 24, 500  # amostras pequenas fazem o ruído sozinho passar do limiar de Wasserstein
CFG = MonitoringConfig()


def make_dataset(shift_last_months: int = 0, shifted: tuple[str, ...] = ("a", "b")) -> Dataset:
    """Três features gaussianas; nas últimas `shift_last_months` as colunas `shifted` ganham +3 desvios."""
    rng = np.random.default_rng(0)
    months = pd.date_range("1996-01-31", periods=N_MONTHS, freq="ME")
    frames = []
    for i, m in enumerate(months):
        df = pd.DataFrame({c: rng.normal(0, 1, N_ACCOUNTS) for c in ("a", "b", "c")})
        if i >= N_MONTHS - shift_last_months:
            df[list(shifted)] += 3
        frames.append(df.assign(timestamp=m))
    df = pd.concat(frames, ignore_index=True)
    return Dataset(X=df[["a", "b", "c"]], y=pd.Series(rng.normal(size=len(df))), timestamps=df["timestamp"])


def cfg_for(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(kaggle=KaggleConfig(dataset="x/y"), paths=PathsConfig(data_dir=tmp_path), monitoring=CFG)


def test_no_drift_when_windows_come_from_the_same_distribution() -> None:
    rng = np.random.default_rng(1)
    ref = pd.DataFrame(rng.normal(size=(1000, 3)), columns=["a", "b", "c"])
    cur = pd.DataFrame(rng.normal(size=(1000, 3)), columns=["a", "b", "c"])
    _, summary = compute_drift(ref, cur, CFG)
    assert summary.n_drifted == 0
    assert not summary.drift_detected
    assert not any(f.drifted for f in summary.features.values())


def test_injected_drift_is_detected_only_in_shifted_columns() -> None:
    rng = np.random.default_rng(1)
    ref = pd.DataFrame(rng.normal(size=(1000, 3)), columns=["a", "b", "c"])
    cur = pd.DataFrame(rng.normal(size=(1000, 3)), columns=["a", "b", "c"]).assign(a=lambda d: d["a"] + 3)
    _, summary = compute_drift(ref, cur, CFG)
    assert {c for c, f in summary.features.items() if f.drifted} == {"a"}
    assert summary.n_drifted == 1
    assert summary.drift_share == pytest.approx(1 / 3)
    assert not summary.drift_detected  # 1/3 < 0,5


def test_dataset_drift_needs_the_share_threshold() -> None:
    rng = np.random.default_rng(1)
    ref = pd.DataFrame(rng.normal(size=(1000, 4)), columns=list("abcd"))
    cur = pd.DataFrame(rng.normal(size=(1000, 4)), columns=list("abcd")).assign(
        a=lambda d: d.a + 3, b=lambda d: d.b + 3
    )
    _, summary = compute_drift(ref, cur, CFG)
    assert summary.drift_share == 0.5
    assert summary.drift_detected  # exatamente no limiar conta como drift


def test_summary_matches_evidently_count() -> None:
    rng = np.random.default_rng(2)
    ref = pd.DataFrame(rng.normal(size=(800, 3)), columns=["a", "b", "c"])
    cur = pd.DataFrame(rng.normal(size=(800, 3)), columns=["a", "b", "c"]).assign(b=lambda d: d["b"] + 3)
    snapshot, summary = compute_drift(ref, cur, CFG)
    evidently = next(
        m["value"] for m in snapshot.dict()["metrics"] if m["config"]["type"].endswith(":DriftedColumnsCount")
    )
    assert summary.n_drifted == evidently["count"]
    assert summary.drift_share == pytest.approx(evidently["share"])


def test_nulls_do_not_break_the_report() -> None:
    rng = np.random.default_rng(3)
    ref = pd.DataFrame(rng.normal(size=(500, 2)), columns=["a", "b"])
    cur = ref.copy()
    cur.loc[:50, "a"] = np.nan
    _, summary = compute_drift(ref, cur, CFG)
    assert summary.n_features == 2


@pytest.mark.parametrize(
    "ref,cur",
    [(pd.DataFrame({"a": []}), pd.DataFrame({"a": [1.0]})), (pd.DataFrame({"a": [1.0]}), pd.DataFrame({"b": [1.0]}))],
)
def test_compute_drift_validates_inputs(ref: pd.DataFrame, cur: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        compute_drift(ref, cur, CFG)


def test_select_windows_uses_train_val_as_reference_and_last_months_as_current() -> None:
    ds = make_dataset()
    split = chronological_split(ds.timestamps, GlobalConfig(kaggle=KaggleConfig(dataset="x/y")).training.split)
    ref, cur, ref_window, cur_window = select_windows(ds, split, 3)
    assert len(cur) == 3 * N_ACCOUNTS
    assert cur_window.endswith(str(ds.timestamps.max().date()))
    assert cur_window.startswith(str(sorted(ds.timestamps.unique())[-3].date())[:10])
    assert len(ref) == int((split.train | split.val).sum())
    assert ref_window.startswith("1996-01-31")


def test_select_windows_rejects_window_invading_the_reference() -> None:
    ds = make_dataset()
    split = chronological_split(ds.timestamps, GlobalConfig(kaggle=KaggleConfig(dataset="x/y")).training.split)
    with pytest.raises(ValueError, match="invade"):
        select_windows(ds, split, N_MONTHS - 2)
    with pytest.raises(ValueError, match="fora de"):
        select_windows(ds, split, 0)


def test_run_drift_writes_report_and_summary(tmp_path: Path) -> None:
    summary = run_drift(cfg_for(tmp_path), make_dataset(shift_last_months=3, shifted=("a", "b", "c")))
    assert summary.drift_detected and summary.n_drifted == 3
    assert (tmp_path / "monitoring" / "drift_report.html").stat().st_size > 0
    saved = json.loads((tmp_path / "monitoring" / "drift_summary.json").read_text())
    assert saved["drift_detected"] is True
    assert saved["current_window"].endswith(str(pd.Timestamp("1997-12-31").date()))
    assert set(saved["features"]) == {"a", "b", "c"}


def test_run_drift_without_shift_reports_no_drift(tmp_path: Path) -> None:
    summary = run_drift(cfg_for(tmp_path), make_dataset())
    assert not summary.drift_detected


def test_cli_returns_error_code_when_step_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("falhou")

    monkeypatch.setattr("the_bank_project.monitoring.cli.run_drift", boom)
    assert main(["drift"]) == 1
