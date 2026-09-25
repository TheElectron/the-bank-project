import mlflow
import numpy as np
import pytest
from mlflow import MlflowClient
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import LinearRegression

from the_bank_project.config import GlobalConfig
from the_bank_project.training.dataset import Dataset
from the_bank_project.training.registry import promote
from the_bank_project.training.tracking import configure_mlflow


def _register(cfg: GlobalConfig, model: object, alias: str | None) -> str:
    """Registra `model` como nova versão (e aponta `alias` para ela)."""
    with mlflow.start_run():
        info = mlflow.sklearn.log_model(model, name="model", serialization_format="cloudpickle")
    version = mlflow.register_model(info.model_uri, cfg.training.registered_model).version
    if alias:
        MlflowClient().set_registered_model_alias(cfg.training.registered_model, alias, version)
    return str(version)


@pytest.fixture
def models(cfg: GlobalConfig, dataset: Dataset) -> dict[str, object]:
    configure_mlflow(cfg)
    good = LinearRegression().fit(dataset.X[["outflow_3m_avg"]], dataset.y)
    bad = DummyRegressor(strategy="mean").fit(dataset.X[["outflow_3m_avg"]], dataset.y)
    return {"good": _Cols(good), "bad": _Cols(bad)}


class _Cols:
    """Usa só `outflow_3m_avg`, para o modelo aceitar o mesmo X do dataset sintético."""

    def __init__(self, model: object) -> None:
        self.model = model

    def predict(self, X):  # type: ignore[no-untyped-def]
        return np.asarray(self.model.predict(X[["outflow_3m_avg"]]))  # type: ignore[attr-defined]


def _alias(cfg: GlobalConfig, alias: str) -> str | None:
    try:
        return str(MlflowClient().get_model_version_by_alias(cfg.training.registered_model, alias).version)
    except mlflow.exceptions.MlflowException:
        return None


def test_promote_without_challenger_fails(cfg: GlobalConfig, dataset: Dataset):
    with pytest.raises(LookupError, match="challenger"):
        promote(cfg, dataset)


def test_first_challenger_becomes_champion(cfg: GlobalConfig, dataset: Dataset, models: dict[str, object]):
    v = _register(cfg, models["bad"], "challenger")
    result = promote(cfg, dataset)
    assert result.decision == "promoted_first" and _alias(cfg, "champion") == v


def test_promote_is_a_noop_when_challenger_is_already_champion(
    cfg: GlobalConfig, dataset: Dataset, models: dict[str, object]
):
    v = _register(cfg, models["good"], "challenger")
    promote(cfg, dataset)
    assert promote(cfg, dataset).decision == "noop" and _alias(cfg, "champion") == v


def test_better_challenger_replaces_the_champion(cfg: GlobalConfig, dataset: Dataset, models: dict[str, object]):
    old = _register(cfg, models["bad"], "champion")
    new = _register(cfg, models["good"], "challenger")
    result = promote(cfg, dataset)
    assert result.decision == "promoted" and result.challenger_mae < result.champion_mae
    assert _alias(cfg, "champion") == new != old


def test_worse_challenger_is_rejected_and_champion_stays(
    cfg: GlobalConfig, dataset: Dataset, models: dict[str, object]
):
    champion = _register(cfg, models["good"], "champion")
    challenger = _register(cfg, models["bad"], "challenger")
    result = promote(cfg, dataset)
    assert result.decision == "kept" and result.challenger_mae > result.champion_mae
    assert _alias(cfg, "champion") == champion
    assert MlflowClient().get_model_version(cfg.training.registered_model, challenger).tags["gate"] == "rejected"


def test_equal_challenger_does_not_replace_the_champion(cfg: GlobalConfig, dataset: Dataset, models: dict[str, object]):
    champion = _register(cfg, models["good"], "champion")
    _register(cfg, models["good"], "challenger")
    assert promote(cfg, dataset).decision == "kept" and _alias(cfg, "champion") == champion  # "supera" é estrito
