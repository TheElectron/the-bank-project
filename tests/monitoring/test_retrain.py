"""Decisão de re-treino por drift: função pura, estado do cooldown, CLI e métrica."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from the_bank_project.config import GlobalConfig, KaggleConfig, MonitoringConfig, PathsConfig
from the_bank_project.monitoring import (
    DriftCollector,
    DriftSummary,
    FeatureDrift,
    decide_retrain,
    load_last_retrain,
    record_retrain,
    should_retrain,
)
from the_bank_project.monitoring import cli as monitoring_cli
from the_bank_project.monitoring.drift import SUMMARY_FILE

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
CFG = MonitoringConfig(retrain_cooldown_days=14)


def make_summary(detected: bool = True) -> DriftSummary:
    return DriftSummary(
        reference_window="a", current_window="b", reference_rows=10, current_rows=3, n_features=1,
        n_drifted=int(detected), drift_share=float(detected), drift_detected=detected, feature_threshold=0.1,
        drift_share_threshold=0.5, features={"a": FeatureDrift(score=0.4, drifted=detected)}, generated_at=NOW,
    )  # fmt: skip


def test_no_drift_never_retrains() -> None:
    d = should_retrain(make_summary(detected=False), None, NOW, CFG)
    assert (d.retrain, d.reason) == (False, "no_drift")


def test_drift_without_previous_retrain_triggers() -> None:
    d = should_retrain(make_summary(), None, NOW, CFG)
    assert (d.retrain, d.reason) == (True, "retrain")


def test_cooldown_blocks_until_it_expires() -> None:
    inside = should_retrain(make_summary(), NOW - timedelta(days=14) + timedelta(seconds=1), NOW, CFG)
    exact = should_retrain(make_summary(), NOW - timedelta(days=14), NOW, CFG)
    assert (inside.retrain, inside.reason) == (False, "cooldown")
    assert (exact.retrain, exact.reason) == (True, "retrain")


def test_disabled_wins_over_drift() -> None:
    d = should_retrain(make_summary(), None, NOW, CFG.model_copy(update={"retrain_enabled": False}))
    assert (d.retrain, d.reason) == (False, "disabled")


def make_cfg(tmp_path: Path, detected: bool = True) -> GlobalConfig:
    out = tmp_path / "monitoring"
    out.mkdir()
    (out / SUMMARY_FILE).write_text(make_summary(detected).model_dump_json())
    return GlobalConfig(
        paths=PathsConfig(data_dir=tmp_path), kaggle=KaggleConfig(dataset="x/y"), monitoring=CFG,
    )  # fmt: skip


def test_decide_records_cooldown_and_second_call_is_blocked(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    assert load_last_retrain(cfg.paths.monitoring) is None
    assert decide_retrain(cfg, now=NOW).retrain is True
    assert load_last_retrain(cfg.paths.monitoring) == NOW
    later = decide_retrain(cfg, now=NOW + timedelta(days=7))
    assert (later.retrain, later.reason) == (False, "cooldown")
    assert decide_retrain(cfg, now=NOW + timedelta(days=14)).retrain is True


def test_decide_without_record_leaves_no_state(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    assert decide_retrain(cfg, now=NOW, record=False).retrain is True
    assert load_last_retrain(cfg.paths.monitoring) is None


def test_no_drift_does_not_touch_state(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path, detected=False)
    assert decide_retrain(cfg, now=NOW).reason == "no_drift"
    assert load_last_retrain(cfg.paths.monitoring) is None


def test_missing_summary_raises(tmp_path: Path) -> None:
    cfg = GlobalConfig(paths=PathsConfig(data_dir=tmp_path), kaggle=KaggleConfig(dataset="x/y"))
    with pytest.raises(FileNotFoundError):
        decide_retrain(cfg, now=NOW)


def test_record_creates_missing_directory(tmp_path: Path) -> None:
    record_retrain(tmp_path / "novo" / "dir", NOW)
    assert load_last_retrain(tmp_path / "novo" / "dir") == NOW


def test_collector_exposes_last_retrain_only_when_known() -> None:
    def render(at: datetime | None) -> str:
        registry = CollectorRegistry()
        registry.register(DriftCollector(make_summary(), at))
        return generate_latest(registry).decode()

    assert "retrain_last_timestamp_seconds" not in render(None)
    line = next(x for x in render(NOW).splitlines() if x.startswith("retrain_last_timestamp_seconds "))
    assert float(line.split()[1]) == pytest.approx(NOW.timestamp())


def test_cli_retrain_check_does_not_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(monitoring_cli, "load_config", lambda: cfg)
    assert monitoring_cli.main(["retrain-check"]) == 0
    assert load_last_retrain(cfg.paths.monitoring) is None
