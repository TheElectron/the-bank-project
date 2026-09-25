"""Configuração do MLflow: tracking URI, experimento e nomes de run."""

from datetime import date
from pathlib import Path

import mlflow

from the_bank_project.config import GlobalConfig, Settings


def tracking_uri(cfg: GlobalConfig) -> str:
    """URI do tracking: `MLFLOW_TRACKING_URI` do ambiente > config > SQLite local em `data/mlflow/`."""
    uri = Settings().mlflow_tracking_uri or cfg.training.tracking_uri
    if uri:
        return uri
    root = cfg.paths.data / "mlflow"
    root.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{root / 'mlflow.db'}"


def configure_mlflow(cfg: GlobalConfig) -> str:
    """Aponta o MLflow para o tracking configurado e seleciona (criando, se preciso) o experimento.

    Com SQLite local os artefatos ficam em `data/mlflow/artifacts`; com servidor, quem decide é ele.
    """
    uri = tracking_uri(cfg)
    mlflow.set_tracking_uri(uri)
    name = cfg.training.experiment
    if mlflow.get_experiment_by_name(name) is None:
        location = None
        if uri.startswith("sqlite:"):
            location = (Path(uri.removeprefix("sqlite:///")).parent / "artifacts").resolve().as_uri()
        mlflow.create_experiment(name, artifact_location=location)
    mlflow.set_experiment(name)
    return uri


def run_name(stage: str, model: str, day: date | None = None) -> str:
    """Nome de run no padrão do projeto: `<etapa>_<modelo>_<data>`."""
    return f"{stage}_{model}_{(day or date.today()).isoformat()}"
