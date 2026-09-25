"""Dataset de treino: labels + features do Feast (join point-in-time)."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from the_bank_project.features import get_offline_features
from the_bank_project.training.labels import LABELS_TABLE, TARGET

KEYS = ["account_id", "event_timestamp"]


@dataclass(frozen=True)
class Dataset:
    """Uma linha por (conta, mês T), ordenadas no tempo. `X` só tem as features do Feast."""

    X: pd.DataFrame
    y: pd.Series
    timestamps: pd.Series  # instante T de cada linha (para o split cronológico)


def load_dataset(gold_dir: Path, feature_service: str, repo_path: Path | None = None) -> Dataset:
    """Junta os labels às features vigentes em cada `event_timestamp`.

    Raises:
        FileNotFoundError: se os labels não existirem.
        ValueError: se o Feast não devolver features para alguma linha dos labels.
    """
    path = gold_dir / f"{LABELS_TABLE}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} não existe. Gere os labels antes (`make labels`).")
    labels = pd.read_parquet(path)
    entities = labels[KEYS].assign(event_timestamp=labels["event_timestamp"].dt.tz_localize("UTC"))
    features = get_offline_features(entities, feature_service, repo_path)
    features["event_timestamp"] = (
        features["event_timestamp"].dt.tz_localize(None).astype(labels["event_timestamp"].dtype)
    )
    features["account_id"] = features["account_id"].astype(labels["account_id"].dtype)
    df = labels.merge(features, on=KEYS, how="left", validate="1:1")
    feature_cols = [c for c in features.columns if c not in KEYS]
    if len(features) != len(labels) or df[feature_cols].isna().all(axis=1).any():
        raise ValueError("O Feast não devolveu features para todas as linhas dos labels.")
    df = df.sort_values(KEYS, ignore_index=True)
    # float64 em tudo: schema estável no modelo registrado (o serving envia o mesmo tipo)
    return Dataset(X=df[feature_cols].astype("float64"), y=df[TARGET], timestamps=df["event_timestamp"])
