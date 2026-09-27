"""Tuning de hiperparâmetros com Optuna (TPE) e validação cruzada temporal.

As dobras usam só os meses de **treino**: a validação continua limpa para escolher o campeão entre os
algoritmos e o teste para a avaliação final. Requer o grupo `tuning` do Poetry (dev/CI); o treino em
produção só lê o resultado (`tuned_params`).
"""

import logging
import time
from datetime import UTC, date, datetime
from pathlib import Path

import mlflow
import numpy as np
import optuna

from the_bank_project.config import GlobalConfig
from the_bank_project.training.cv import expanding_folds
from the_bank_project.training.dataset import Dataset
from the_bank_project.training.evaluate import regression_metrics
from the_bank_project.training.models import CANDIDATES, Candidate, Params, SpaceSpec, make_estimator
from the_bank_project.training.tracking import configure_mlflow, run_name
from the_bank_project.training.train import prepare
from the_bank_project.training.tuned_params import BestParams, TunedModel, best_params_path, save_best_params

logger = logging.getLogger(__name__)

Folds = list[tuple[np.ndarray, np.ndarray]]


def suggest(trial: optuna.Trial, space: dict[str, SpaceSpec]) -> Params:
    """Sorteia uma configuração do espaço (`int`, `float`, `log` ou `cat`)."""
    params: Params = {}
    for name, (kind, *args) in space.items():
        if kind == "int":
            params[name] = trial.suggest_int(name, args[0], args[1])
        elif kind in ("float", "log"):
            params[name] = trial.suggest_float(name, args[0], args[1], log=kind == "log")
        elif kind == "cat":
            params[name] = trial.suggest_categorical(name, args[0])
        else:
            raise ValueError(f"Tipo de espaço desconhecido para '{name}': {kind}")
    return params


def cv_mae(cand: Candidate, params: Params, ds: Dataset, folds: Folds, cfg: GlobalConfig) -> tuple[float, list[float]]:
    """MAE médio (escala original) de `params` nas dobras, e o MAE de cada dobra."""
    tc = cfg.training
    maes = []
    for train, val in folds:
        model = make_estimator(cand, params, tc.seed, tc.log_target).fit(ds.X[train], ds.y[train])
        maes.append(regression_metrics(ds.y[val], model.predict(ds.X[val]))["mae"])
    return float(np.mean(maes)), maes


def tune_candidate(cand: Candidate, ds: Dataset, folds: Folds, cfg: GlobalConfig, day: date) -> TunedModel:
    """Busca a melhor configuração de um modelo; se nenhuma bater a padrão nas mesmas dobras, mantém a padrão."""
    tc, tu = cfg.training, cfg.tuning
    with mlflow.start_run(run_name=run_name("tuning", cand.name, day)):
        default_mae, _ = cv_mae(cand, cand.defaults, ds, folds, cfg)
        mlflow.log_metric("default_cv_mae", default_mae)

        def objective(trial: optuna.Trial) -> float:
            params = {**cand.defaults, **suggest(trial, cand.tune_space)}
            with mlflow.start_run(run_name=f"trial_{cand.name}_{trial.number}", nested=True):
                mean, per_fold = cv_mae(cand, params, ds, folds, cfg)
                mlflow.log_params(params)
                mlflow.log_metrics({"cv_mae": mean, **{f"fold{i}_mae": v for i, v in enumerate(per_fold)}})
            return mean

        study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=tc.seed))
        start = time.monotonic()
        study.optimize(objective, n_trials=tu.n_trials, timeout=tu.timeout_minutes * 60)
        best = {**cand.defaults, **study.best_params} if study.trials else cand.defaults
        best_mae = study.best_value if study.trials else default_mae
        won = best_mae < default_mae
        mlflow.log_params({f"best_{k}": v for k, v in best.items()})
        mlflow.log_metrics({"best_cv_mae": min(best_mae, default_mae), "n_trials": len(study.trials)})
        logger.info("%s: padrão %.0f -> %s %.0f (CV MAE, %d tentativas em %.0f s).", cand.name, default_mae,
                    "ajustado" if won else "padrão mantido", best_mae if won else default_mae, len(study.trials),
                    time.monotonic() - start)  # fmt: skip
    return TunedModel(
        params=best if won else dict(cand.defaults), cv_mae=min(best_mae, default_mae), default_cv_mae=default_mae,
        n_trials=len(study.trials), source="tuned" if won else "default",
    )  # fmt: skip


def run_tuning(
    cfg: GlobalConfig, dataset: Dataset | None = None, day: date | None = None, out: Path | None = None
) -> BestParams:
    """Ajusta todos os candidatos com espaço de busca e grava `best_params.yaml`.

    Raises:
        ValueError: se os meses de treino não bastarem para as dobras configuradas.
    """
    day = day or date.today()
    ds, split = prepare(cfg, dataset)
    configure_mlflow(cfg)
    folds = expanding_folds(ds.timestamps, split.train, cfg.tuning.cv_folds, cfg.training.split.gap_months)
    logger.info("Tuning em %d dobras dentro de %s", len(folds), split.describe()["train_window"])
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    models = {c.name: tune_candidate(c, ds, folds, cfg, day) for c in CANDIDATES if c.tune_space}
    best = BestParams(
        generated_at=datetime.now(UTC), seed=cfg.training.seed, log_target=cfg.training.log_target,
        cv_folds=cfg.tuning.cv_folds, tuned_window=split.describe()["train_window"], models=models,
    )  # fmt: skip
    save_best_params(best, out or best_params_path(cfg))
    return best
