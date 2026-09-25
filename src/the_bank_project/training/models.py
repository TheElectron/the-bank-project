"""Modelos candidatos e seus espaços de busca. Todos entram como pipelines do scikit-learn."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import ParameterSampler
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

Params = dict[str, Any]


@dataclass(frozen=True)
class Candidate:
    """Um modelo candidato: como construir o estimador e o que variar na busca."""

    name: str
    build: Callable[[Params, int], Any]
    defaults: Params = field(default_factory=dict)
    space: dict[str, list[Any]] = field(default_factory=dict)
    supports_log_target: bool = True


def _linear(params: Params, seed: int) -> Pipeline:
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LinearRegression())


def _forest(params: Params, seed: int) -> RandomForestRegressor:
    return RandomForestRegressor(random_state=seed, n_jobs=-1, **params)  # NaN nativo (sklearn >= 1.4)


def _hist_gb(params: Params, seed: int) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(random_state=seed, **params)


def _xgboost(params: Params, seed: int) -> XGBRegressor:
    return XGBRegressor(random_state=seed, n_jobs=-1, tree_method="hist", **params)


CANDIDATES = (
    # Sem log no alvo: a regressão linear extrapola em log1p e o expm1 explode (MAE de validação 32 mil contra
    # 8 mil sem o log, medido em 2026-09-24). Como baseline ela precisa ser sã.
    Candidate("regressao_linear", _linear, supports_log_target=False),
    Candidate(
        "random_forest",
        _forest,
        defaults={"n_estimators": 150, "max_depth": 12, "min_samples_leaf": 5, "max_features": 0.5},
        space={
            "n_estimators": [100, 200],
            "max_depth": [8, 12, 16],
            "min_samples_leaf": [3, 5, 10, 20],
            "max_features": [0.3, 0.5, 0.8],
        },
    ),  # fmt: skip
    Candidate(
        "gradient_boosting",
        _hist_gb,
        defaults={"max_iter": 300, "learning_rate": 0.05, "max_depth": 6, "min_samples_leaf": 20},
        space={
            "max_iter": [200, 400],
            "learning_rate": [0.03, 0.05, 0.1],
            "max_depth": [4, 6, 8],
            "min_samples_leaf": [10, 20, 50],
            "l2_regularization": [0.0, 1.0, 10.0],
        },
    ),  # fmt: skip
    Candidate(
        "xgboost",
        _xgboost,
        defaults={
            "n_estimators": 400,
            "learning_rate": 0.05,
            "max_depth": 6,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
        },
        space={
            "n_estimators": [300, 500],
            "learning_rate": [0.03, 0.05, 0.1],
            "max_depth": [4, 6, 8],
            "subsample": [0.7, 0.8, 1.0],
            "colsample_bytree": [0.6, 0.8, 1.0],
            "min_child_weight": [1, 5, 10],
        },
    ),  # fmt: skip
)


def make_estimator(candidate: Candidate, params: Params, seed: int, log_target: bool) -> Any:
    """Constrói o estimador; com `log_target` (e se o modelo suporta), treina em `log1p(y)` e reverte na predição."""
    model = candidate.build(params, seed)
    if not (log_target and candidate.supports_log_target):
        return model
    return TransformedTargetRegressor(regressor=model, func=np.log1p, inverse_func=np.expm1)


def trial_params(candidate: Candidate, n_trials: int, seed: int) -> list[Params]:
    """Configuração padrão + `n_trials` sorteios do espaço de busca (sem repetir a padrão)."""
    trials = [candidate.defaults]
    if candidate.space and n_trials > 0:
        for sample in ParameterSampler(candidate.space, n_iter=n_trials, random_state=seed):
            merged = {**candidate.defaults, **sample}
            if merged not in trials:
                trials.append(merged)
    return trials
