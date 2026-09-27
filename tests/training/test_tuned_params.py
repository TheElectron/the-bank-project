"""`best_params.yaml`: schema, ida e volta, e quando é ignorado."""

import logging
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from the_bank_project.config import GlobalConfig, KaggleConfig, TuningConfig
from the_bank_project.training import tuned_params
from the_bank_project.training.tuned_params import (
    BestParams,
    TunedModel,
    best_params_path,
    load_best_params,
    save_best_params,
)


def make_best(log_target: bool = True) -> BestParams:
    model = TunedModel(params={"max_depth": 7, "learning_rate": 0.05}, cv_mae=7000.0, default_cv_mae=7200.0,
                       n_trials=12, source="tuned")  # fmt: skip
    return BestParams(generated_at=datetime(2026, 9, 26, tzinfo=UTC), seed=42, log_target=log_target, cv_folds=4,
                      tuned_window="1993-01-31..1996-12-31 (100 linhas)", models={"xgboost": model})  # fmt: skip


@pytest.fixture
def cfg() -> GlobalConfig:
    return GlobalConfig(kaggle=KaggleConfig(dataset="o/d"), tuning=TuningConfig(best_params_file="bp.yaml"))


def test_path_is_relative_to_configs_dir_unless_absolute(cfg: GlobalConfig) -> None:
    assert best_params_path(cfg) == tuned_params.CONFIGS_DIR / "bp.yaml"


def test_missing_file_means_no_tuning_yet(cfg: GlobalConfig) -> None:
    assert load_best_params(cfg) is None


def test_roundtrip_keeps_everything(cfg: GlobalConfig) -> None:
    path = best_params_path(cfg)
    path.parent.mkdir(parents=True)
    save_best_params(make_best(), path)
    assert path.read_text().startswith("# Gerado por `make tune`")
    assert load_best_params(cfg) == make_best()


def test_params_tuned_with_another_target_transform_are_ignored(
    cfg: GlobalConfig, caplog: pytest.LogCaptureFixture
) -> None:
    path = best_params_path(cfg)
    path.parent.mkdir(parents=True)
    save_best_params(make_best(log_target=False), path)
    with caplog.at_level(logging.WARNING):
        assert load_best_params(cfg) is None
    assert "log_target" in caplog.text


def test_invalid_file_fails_loudly(cfg: GlobalConfig) -> None:
    path = best_params_path(cfg)
    path.parent.mkdir(parents=True)
    path.write_text("models: {xgboost: {params: {}, source: bogus}}\n")
    with pytest.raises(ValidationError):
        load_best_params(cfg)


def test_repo_config_has_the_tuning_section() -> None:
    from the_bank_project.config import load_config

    assert load_config().tuning == TuningConfig()  # o YAML do repositório espelha os padrões do schema
