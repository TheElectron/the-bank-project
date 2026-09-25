"""Métricas e baselines ingênuos. As mesmas métricas valem para todos os runs."""

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

# Baselines sem treino: prever o outflow do mês atual, ou a média dos últimos 3 meses.
NAIVE_BASELINES = {"naive_persistencia": "outflow_amount", "naive_media_3m": "outflow_3m_avg"}


def regression_metrics(y_true: pd.Series | np.ndarray, y_pred: pd.Series | np.ndarray) -> dict[str, float]:
    """MAE, RMSE e R², na escala original do alvo."""
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(root_mean_squared_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def skill_score(mae: float, naive_mae: float) -> float:
    """`1 - MAE/MAE_ingênuo`: > 0 só se o modelo bate o melhor baseline sem treino."""
    return 1.0 - mae / naive_mae


def evaluate(predict: Callable[[pd.DataFrame], np.ndarray], X: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    """Métricas de um preditor em `X`, `y`."""
    return regression_metrics(y, predict(X))
