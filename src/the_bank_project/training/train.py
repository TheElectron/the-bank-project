"""Treino dos candidatos: seleção na validação, avaliação única no teste, tudo no MLflow."""

import logging
from dataclasses import dataclass
from datetime import date

import mlflow
import numpy as np
import pandas as pd
from mlflow import MlflowClient
from mlflow.models import infer_signature

from the_bank_project.config import GlobalConfig
from the_bank_project.training.dataset import Dataset, load_dataset
from the_bank_project.training.evaluate import NAIVE_BASELINES, regression_metrics, skill_score
from the_bank_project.training.models import CANDIDATES, Candidate, Params, make_estimator, trial_params
from the_bank_project.training.split import Split, chronological_split
from the_bank_project.training.tracking import configure_mlflow, run_name

logger = logging.getLogger(__name__)

CHALLENGER = "challenger"


@dataclass(frozen=True)
class ModelResult:
    """Resultado de um candidato (ou baseline): métricas de validação e de teste."""

    name: str
    run_id: str
    val: dict[str, float]
    test: dict[str, float]


@dataclass(frozen=True)
class TrainingResult:
    """Resumo do treino: todos os runs, o vencedor pela validação e a versão registrada."""

    baselines: list[ModelResult]
    candidates: list[ModelResult]
    winner: ModelResult
    version: str


def prepare(cfg: GlobalConfig, dataset: Dataset | None = None) -> tuple[Dataset, Split]:
    """Carrega o dataset (Feast + labels) e o divide cronologicamente."""
    ds = dataset or load_dataset(cfg.paths.gold, cfg.training.feature_service, cfg.feast.repo)
    return ds, chronological_split(ds.timestamps, cfg.training.split)


def _log_metrics(prefix: str, metrics: dict[str, float]) -> None:
    mlflow.log_metrics({f"{prefix}_{k}": v for k, v in metrics.items()})


def _run_baselines(ds: Dataset, split: Split, day: date) -> list[ModelResult]:
    results = []
    for name, column in NAIVE_BASELINES.items():
        with mlflow.start_run(run_name=run_name("treino", name, day)) as run:
            val = regression_metrics(ds.y[split.val], ds.X.loc[split.val, column])
            test = regression_metrics(ds.y[split.test], ds.X.loc[split.test, column])
            mlflow.set_tags({"model_kind": "baseline", "predictor": column, **split.describe()})
            _log_metrics("val", val)
            _log_metrics("test", test)
        results.append(ModelResult(name, run.info.run_id, val, test))
    return results


def _select_params(cand: Candidate, ds: Dataset, split: Split, cfg: GlobalConfig) -> tuple[Params, dict[str, float]]:
    """Ajusta cada configuração só no treino e escolhe a de menor MAE na validação."""
    tc = cfg.training
    best: tuple[Params, dict[str, float]] | None = None
    for i, params in enumerate(trial_params(cand, tc.n_tuning_trials, tc.seed)):
        with mlflow.start_run(run_name=f"trial_{cand.name}_{i}", nested=True):
            model = make_estimator(cand, params, tc.seed, tc.log_target).fit(ds.X[split.train], ds.y[split.train])
            val = regression_metrics(ds.y[split.val], model.predict(ds.X[split.val]))
            mlflow.log_params(params)
            _log_metrics("val", val)
        if best is None or val["mae"] < best[1]["mae"]:
            best = (params, val)
    assert best is not None
    return best


def _run_candidate(
    cand: Candidate, ds: Dataset, split: Split, cfg: GlobalConfig, naive_mae: float, day: date
) -> ModelResult:
    tc = cfg.training
    with mlflow.start_run(run_name=run_name("treino", cand.name, day)) as run:
        params, val = _select_params(cand, ds, split, cfg)
        fit_mask = split.train | split.val  # o modelo final usa treino + validação; o teste fica intocado
        final = make_estimator(cand, params, tc.seed, tc.log_target).fit(ds.X[fit_mask], ds.y[fit_mask])
        pred = final.predict(ds.X[split.test])
        test = regression_metrics(ds.y[split.test], pred)
        mlflow.log_params({**params, "log_target": tc.log_target and cand.supports_log_target, "seed": tc.seed})
        _log_metrics("val", val)
        _log_metrics("test", test)
        mlflow.log_metric("test_skill_vs_naive", skill_score(test["mae"], naive_mae))
        mlflow.set_tags({"model_kind": "candidate", "algorithm": cand.name, "feature_service": tc.feature_service,
                         **split.describe()})  # fmt: skip
        sample = ds.X[split.test].head(5)
        # cloudpickle: o formato padrão (skops) exige listar cada tipo do modelo como "confiável" e a lista muda
        # por algoritmo/versão. O registry é local e só carrega modelos treinados aqui.
        mlflow.sklearn.log_model(
            final,
            name="model",
            signature=infer_signature(sample, final.predict(sample)),
            input_example=sample,
            serialization_format="cloudpickle",
        )
    return ModelResult(cand.name, run.info.run_id, val, test)


def run_training(cfg: GlobalConfig, dataset: Dataset | None = None, day: date | None = None) -> TrainingResult:
    """Treina todos os candidatos, registra o vencedor pela **validação** como `challenger`.

    O teste só é medido depois da seleção, uma vez por modelo, e nunca decide nada aqui: a
    promoção a `champion` é do gate (`registry.promote`).
    """
    day = day or date.today()
    ds, split = prepare(cfg, dataset)
    uri = configure_mlflow(cfg)
    logger.info("Tracking: %s | %s", uri, split.describe())
    baselines = _run_baselines(ds, split, day)
    naive_mae = min(b.test["mae"] for b in baselines)
    candidates = [_run_candidate(c, ds, split, cfg, naive_mae, day) for c in CANDIDATES]
    winner = min(candidates, key=lambda r: r.val["mae"])

    client, name = MlflowClient(), cfg.training.registered_model
    version = mlflow.register_model(f"runs:/{winner.run_id}/model", name).version
    client.set_registered_model_alias(name, CHALLENGER, version)
    client.set_model_version_tag(name, version, "algorithm", winner.name)
    client.set_model_version_tag(name, version, "val_mae", f"{winner.val['mae']:.2f}")
    client.set_model_version_tag(name, version, "test_mae", f"{winner.test['mae']:.2f}")
    _log_summary(baselines, candidates, winner, version)
    return TrainingResult(baselines, candidates, winner, str(version))


def _log_summary(
    baselines: list[ModelResult], candidates: list[ModelResult], winner: ModelResult, version: object
) -> None:
    rows = [(r.name, r.val["mae"], r.test["mae"], r.test["rmse"], r.test["r2"]) for r in [*baselines, *candidates]]
    table = pd.DataFrame(rows, columns=["modelo", "val_mae", "test_mae", "test_rmse", "test_r2"]).round(2)
    logger.info("\n%s", table.to_string(index=False))
    logger.info("Vencedor pela validação: %s (versão %s, alias '%s').", winner.name, version, CHALLENGER)
    if winner.test["mae"] >= min(b.test["mae"] for b in baselines):
        logger.warning("O vencedor NÃO bate o melhor baseline ingênuo no teste (skill <= 0).")
    assert np.isfinite(winner.test["mae"])
