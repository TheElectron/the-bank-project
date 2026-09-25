"""Ciclo de vida no MLflow Model Registry: aliases `challenger` e `champion` e o gate de promoção."""

import logging
from dataclasses import dataclass
from typing import Literal

import mlflow
import numpy as np
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from the_bank_project.config import GlobalConfig
from the_bank_project.training.dataset import Dataset
from the_bank_project.training.evaluate import regression_metrics
from the_bank_project.training.tracking import configure_mlflow
from the_bank_project.training.train import CHALLENGER, prepare

logger = logging.getLogger(__name__)

CHAMPION = "champion"
Decision = Literal["promoted_first", "promoted", "kept", "noop"]


@dataclass(frozen=True)
class Promotion:
    """Resultado do gate. `*_mae` são medidos no **mesmo** teste, agora."""

    decision: Decision
    challenger_version: str
    champion_version: str | None
    challenger_mae: float | None
    champion_mae: float | None


def _version(client: MlflowClient, name: str, alias: str) -> str | None:
    try:
        return str(client.get_model_version_by_alias(name, alias).version)
    except MlflowException:
        return None


def _test_mae(name: str, alias: str, ds: Dataset, mask: np.ndarray) -> float:
    model = mlflow.sklearn.load_model(f"models:/{name}@{alias}")
    return regression_metrics(ds.y[mask], model.predict(ds.X[mask]))["mae"]


def promote(cfg: GlobalConfig, dataset: Dataset | None = None) -> Promotion:
    """Promove o `challenger` a `champion` só se tiver MAE de teste **estritamente menor**.

    Os dois modelos são reavaliados agora no mesmo teste (o dataset pode ter mudado desde que
    o campeão foi treinado). Sem campeão, o challenger assume.

    Raises:
        LookupError: se não houver `challenger` registrado (rode o treino antes).
    """
    configure_mlflow(cfg)
    client, name = MlflowClient(), cfg.training.registered_model
    challenger = _version(client, name, CHALLENGER)
    if challenger is None:
        raise LookupError(f"Sem alias '{CHALLENGER}' em '{name}'. Rode o treino antes.")
    champion = _version(client, name, CHAMPION)
    if champion is None:
        client.set_registered_model_alias(name, CHAMPION, challenger)
        client.set_model_version_tag(name, challenger, "gate", "promoted_first")
        logger.info("Sem campeão: versão %s assumiu o alias '%s'.", challenger, CHAMPION)
        return Promotion("promoted_first", challenger, None, None, None)
    if champion == challenger:
        return Promotion("noop", challenger, champion, None, None)

    ds, split = prepare(cfg, dataset)
    chall_mae = _test_mae(name, CHALLENGER, ds, split.test)
    champ_mae = _test_mae(name, CHAMPION, ds, split.test)
    promoted = chall_mae < champ_mae
    client.set_model_version_tag(name, challenger, "gate", "promoted" if promoted else "rejected")
    client.set_model_version_tag(name, challenger, "gate_test_mae", f"{chall_mae:.2f} vs campeão {champ_mae:.2f}")
    if promoted:
        client.set_registered_model_alias(name, CHAMPION, challenger)
    logger.info("Gate: challenger v%s MAE %.2f vs champion v%s MAE %.2f -> %s.", challenger, chall_mae, champion,
                champ_mae, "PROMOVIDO" if promoted else "mantido o campeão")  # fmt: skip
    return Promotion("promoted" if promoted else "kept", challenger, champion, chall_mae, champ_mae)
