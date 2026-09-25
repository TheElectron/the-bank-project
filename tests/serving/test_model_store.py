import mlflow
import numpy as np
import pandas as pd
import pytest
from mlflow import MlflowClient
from mlflow.models import infer_signature
from sklearn.linear_model import LinearRegression

from the_bank_project.config import GlobalConfig
from the_bank_project.serving.model_store import ModelStore
from the_bank_project.training.tracking import configure_mlflow

SERVICE = ["account_monthly:outflow_3m_avg", "account_monthly:closing_balance"]
WINDOW = "1998-08-31..1998-11-30 (100 linhas)"


@pytest.fixture
def registry(cfg: GlobalConfig):  # type: ignore[no-untyped-def]
    """Registra modelos de brinquedo no MLflow (SQLite temporário) e devolve o `ModelStore` sobre eles."""
    configure_mlflow(cfg)
    name, client = cfg.training.registered_model, MlflowClient()
    rng = np.random.default_rng(0)

    def register(
        columns: list[str], alias: str | None = "champion", mae: float = 5.0, algorithm: str = "xgboost"
    ) -> str:
        X = pd.DataFrame(rng.uniform(1, 100, (40, len(columns))), columns=columns)
        model = LinearRegression().fit(X, X.sum(axis=1))
        with mlflow.start_run(run_name="treino_xgboost_2026-09-24"):
            mlflow.set_tags({"test_window": WINDOW, "model_kind": "candidate", "algorithm": algorithm})
            mlflow.log_metrics({"test_mae": mae, "val_mae": mae + 1})
            info = mlflow.sklearn.log_model(
                model, name="model", signature=infer_signature(X, model.predict(X)), serialization_format="cloudpickle"
            )
        version = mlflow.register_model(info.model_uri, name).version
        client.set_model_version_tag(name, version, "algorithm", algorithm)
        if alias:
            client.set_registered_model_alias(name, alias, version)
        return str(version)

    with mlflow.start_run(run_name="treino_naive_media_3m_2026-09-24"):  # baseline do mesmo treino
        mlflow.set_tags({"test_window": WINDOW, "model_kind": "baseline"})
        mlflow.log_metric("test_mae", 10.0)
    store = ModelStore(cfg, SERVICE)
    return store, register


def test_no_champion_means_no_model(registry):  # type: ignore[no-untyped-def]
    store, _ = registry
    assert store.refresh() is False and store.bundle is None


def test_loads_the_champion_with_signature_metrics_and_comparison(registry):  # type: ignore[no-untyped-def]
    store, register = registry
    register(["outflow_3m_avg", "closing_balance"])
    assert store.refresh() is True
    bundle = store.bundle
    assert bundle and bundle.input_names == ["outflow_3m_avg", "closing_balance"]
    info = bundle.info
    assert (info.version, info.algorithm, info.algorithm_label) == ("1", "xgboost", "XGBoost")
    assert info.metrics["test_mae"] == 5.0 and info.skill_vs_naive == pytest.approx(0.5)  # 1 - 5/10
    assert [(c.name, c.kind, c.champion) for c in info.comparison] == [
        ("xgboost", "candidate", True),
        ("naive_media_3m", "baseline", False),
    ]
    assert info.windows["test_window"] == WINDOW
    assert len(bundle.model.predict(pd.DataFrame({"outflow_3m_avg": [1.0], "closing_balance": [2.0]}))) == 1  # type: ignore[attr-defined]


def test_refresh_is_a_noop_until_the_champion_alias_moves(registry):  # type: ignore[no-untyped-def]
    store, register = registry
    register(["outflow_3m_avg", "closing_balance"])
    assert store.refresh() and store.refresh() is False
    register(["outflow_3m_avg", "closing_balance"], alias="challenger")
    assert store.refresh() is False and store.bundle.info.version == "1"  # type: ignore[union-attr]
    v3 = register(["outflow_3m_avg", "closing_balance"], alias="champion", mae=4.0)
    assert store.refresh() is True and store.bundle.info.version == v3  # type: ignore[union-attr]


def test_incompatible_champion_does_not_replace_the_running_model(registry):  # type: ignore[no-untyped-def]
    store, register = registry
    register(["outflow_3m_avg", "closing_balance"])
    assert store.refresh()
    register(["outflow_3m_avg", "closing_balance", "feature_nova"])  # o Feast não serve `feature_nova`
    assert store.refresh() is False
    assert store.bundle.info.version == "1"  # type: ignore[union-attr]


def test_incompatible_first_champion_leaves_the_api_without_model(registry):  # type: ignore[no-untyped-def]
    store, register = registry
    register(["so_no_modelo"])
    assert store.refresh() is False and store.bundle is None
