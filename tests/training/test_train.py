from collections.abc import Callable
from datetime import date
from pathlib import Path

import mlflow
import pandas as pd
import pytest
from mlflow import MlflowClient

from the_bank_project.config import GlobalConfig
from the_bank_project.training import train as train_module
from the_bank_project.training.dataset import Dataset
from the_bank_project.training.models import CANDIDATES
from the_bank_project.training.split import chronological_split
from the_bank_project.training.tracking import configure_mlflow, run_name
from the_bank_project.training.train import TrainingResult, run_training

DAY = date(2026, 9, 24)
METRICS = {"val_mae", "val_rmse", "val_r2", "test_mae", "test_rmse", "test_r2"}
# Só 2 candidatos nos testes: cada run do MLflow (SQLite) custa alguns segundos, e o que se testa aqui é a
# orquestração; o ajuste de cada algoritmo já é coberto em test_evaluate_models.py.
SMALL = tuple(c for c in CANDIDATES if c.name in {"regressao_linear", "xgboost"})


@pytest.fixture(autouse=True)
def _small_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(train_module, "CANDIDATES", SMALL)


@pytest.fixture(scope="module")
def trained(
    tmp_path_factory: pytest.TempPathFactory, dataset: Dataset, cfg_factory: Callable[[Path], GlobalConfig]
) -> tuple[GlobalConfig, TrainingResult]:
    """Um único treino compartilhado pelos testes que só inspecionam o resultado."""
    cfg = cfg_factory(tmp_path_factory.mktemp("mlflow"))
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("MLFLOW_TRACKING_URI", raising=False)
        mp.setattr(train_module, "CANDIDATES", SMALL)
        return cfg, run_training(cfg, dataset, DAY)


def test_run_name_follows_the_project_pattern():
    assert run_name("treino", "xgboost", DAY) == "treino_xgboost_2026-09-24"


def test_training_logs_one_run_per_model_with_the_same_metrics(trained: tuple[GlobalConfig, TrainingResult]):
    cfg, result = trained
    configure_mlflow(cfg)
    runs = mlflow.search_runs(experiment_names=[cfg.training.experiment])
    top = runs[runs["tags.mlflow.parentRunId"].isna()].set_index("tags.mlflow.runName")
    expected = {f"treino_{n}_{DAY}" for n in ["naive_persistencia", "naive_media_3m", *[c.name for c in SMALL]]}
    assert set(top.index) == expected
    metric_cols = [c for c in top.columns if c.startswith("metrics.")]
    for name in expected:  # baselines e modelos: as mesmas métricas, para a comparação ser justa
        logged = {c.removeprefix("metrics.") for c in metric_cols if pd.notna(top.loc[name, c])}
        assert logged >= METRICS, name
    assert len(runs[runs["tags.mlflow.parentRunId"].notna()]) >= len(SMALL)  # trials aninhados
    assert {r.name for r in result.candidates} == {c.name for c in SMALL}


def test_winner_is_chosen_by_validation_and_registered_as_challenger(
    trained: tuple[GlobalConfig, TrainingResult], dataset: Dataset
):
    cfg, result = trained
    configure_mlflow(cfg)
    assert result.winner.name == min(result.candidates, key=lambda r: r.val["mae"]).name
    version = MlflowClient().get_model_version_by_alias(cfg.training.registered_model, "challenger")
    assert str(version.version) == result.version and version.tags["algorithm"] == result.winner.name
    model = mlflow.sklearn.load_model(f"models:/{cfg.training.registered_model}@challenger")
    assert len(model.predict(dataset.X.head(3))) == 3
    assert result.winner.test["mae"] < min(b.test["mae"] for b in result.baselines)  # o sinal sintético é forte


def test_training_does_not_promote_to_champion(trained: tuple[GlobalConfig, TrainingResult]):
    cfg, _ = trained
    configure_mlflow(cfg)
    with pytest.raises(mlflow.exceptions.MlflowException):
        MlflowClient().get_model_version_by_alias(cfg.training.registered_model, "champion")  # isso é do gate


def test_test_window_never_influences_selection_and_each_training_adds_a_version(cfg: GlobalConfig, dataset: Dataset):
    """Corromper o alvo só no teste não pode mudar o vencedor nem as métricas de validação."""
    first = run_training(cfg, dataset, DAY)
    split = chronological_split(dataset.timestamps, cfg.training.split)
    y = dataset.y.copy()
    y[split.test] = y[split.test] * 5 + 1_000
    second = run_training(cfg, Dataset(dataset.X, y, dataset.timestamps), DAY)
    assert second.winner.name == first.winner.name and (first.version, second.version) == ("1", "2")
    assert {r.name: r.val["mae"] for r in second.candidates} == pytest.approx(
        {r.name: r.val["mae"] for r in first.candidates}
    )
    assert second.winner.test["mae"] > first.winner.test["mae"]
