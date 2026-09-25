"""Modelo campeão do MLflow: carga, contrato com a feature store e detecção de troca de campeão."""

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import mlflow
import numpy as np
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from the_bank_project.config import GlobalConfig
from the_bank_project.serving.feature_catalog import FEATURES, GROUPS
from the_bank_project.serving.schemas import ComparisonRow, ModelInfo
from the_bank_project.training.registry import CHAMPION
from the_bank_project.training.tracking import tracking_uri

logger = logging.getLogger(__name__)

LABELS = {
    "regressao_linear": "Regressão linear",
    "random_forest": "Random Forest",
    "gradient_boosting": "Gradient Boosting",
    "xgboost": "XGBoost",
    "naive_media_3m": "Média dos 3 meses",
    "naive_persistencia": "Repetir o mês atual",
}
RUN_NAME = re.compile(r"^treino_(?P<model>.+)_\d{4}-\d{2}-\d{2}$")


def _importances(model: object, names: list[str]) -> dict[str, float]:
    """Importância global das features, quando o algoritmo a expõe (árvores e XGBoost); vazio nos demais."""
    inner: Any = getattr(model, "regressor_", model)  # TransformedTargetRegressor (alvo em log1p)
    inner = inner[-1] if hasattr(inner, "steps") else inner  # Pipeline: o último passo é o estimador
    values = getattr(inner, "feature_importances_", None)
    if values is None or len(values) != len(names):
        return {}
    return {n: float(v) for n, v in zip(names, values, strict=True)}


class ContractError(RuntimeError):
    """O modelo espera features que a feature store não serve (ou o contrário)."""


class Predictor(Protocol):
    """O que a API pede ao modelo do MLflow (um estimador ou pipeline do scikit-learn)."""

    def predict(self, X: pd.DataFrame) -> np.ndarray: ...


@dataclass(frozen=True)
class ModelBundle:
    """Um modelo carregado: o estimador, a ordem das colunas de entrada e o que a interface mostra dele."""

    model: Predictor
    input_names: list[str]
    info: ModelInfo


class ModelStore:
    """Mantém o `champion` em memória e o troca, sem parar o servidor, quando o alias muda."""

    def __init__(self, cfg: GlobalConfig, service_features: list[str], client: MlflowClient | None = None) -> None:
        mlflow.set_tracking_uri(tracking_uri(cfg))
        self._cfg = cfg
        self._service = {ref.split(":", 1)[1] for ref in service_features}
        self._client = client or MlflowClient()
        self._lock = threading.Lock()
        self._bundle: ModelBundle | None = None

    @property
    def bundle(self) -> ModelBundle | None:
        return self._bundle

    def _champion_version(self) -> str | None:
        try:
            return str(self._client.get_model_version_by_alias(self._cfg.training.registered_model, CHAMPION).version)
        except MlflowException:
            return None

    def refresh(self) -> bool:
        """Carrega o campeão se ele mudou desde a última carga. Um campeão incompatível não substitui o atual."""
        version = self._champion_version()
        if version is None or (self._bundle and self._bundle.info.version == version):
            return False
        try:
            bundle = self._load(version)
        except Exception:
            logger.exception("Falha ao carregar o campeão v%s; mantendo o modelo atual.", version)
            return False
        with self._lock:
            self._bundle = bundle
        logger.info("Campeão carregado: v%s (%s).", version, bundle.info.algorithm)
        return True

    def _load(self, version: str) -> ModelBundle:
        name = self._cfg.training.registered_model
        uri = f"models:/{name}/{version}"
        model = mlflow.sklearn.load_model(uri)
        signature = mlflow.models.get_model_info(uri).signature
        if signature is None or signature.inputs is None:
            raise ContractError(f"O modelo {name} v{version} não tem assinatura de entrada.")
        names = list(signature.inputs.input_names())
        missing, extra = sorted(set(names) - self._service), sorted(self._service - set(names))
        if missing or extra:
            raise ContractError(f"Modelo x feature store divergem. Só no modelo: {missing}; só no Feast: {extra}.")
        return ModelBundle(model, names, self._describe(version, names, model))

    def _describe(self, version: str, names: list[str], model: object) -> ModelInfo:
        name = self._cfg.training.registered_model
        mv = self._client.get_model_version(name, version)
        algorithm = mv.tags.get("algorithm", "desconhecido")
        run = self._client.get_run(mv.run_id) if mv.run_id else None
        tags = run.data.tags if run else {}
        metrics = {k: float(v) for k, v in (run.data.metrics if run else {}).items() if k.startswith(("val_", "test_"))}
        windows = {k: v for k, v in tags.items() if k.endswith("_window")}
        comparison = self._comparison(windows.get("test_window"), algorithm)
        naive = [c.test_mae for c in comparison if c.kind == "baseline"]
        skill = 1 - metrics["test_mae"] / min(naive) if naive and "test_mae" in metrics else None
        importance = _importances(model, names)
        known = sorted((FEATURES[n] for n in names if n in FEATURES), key=lambda f: GROUPS.index(f.group))
        features = [{**f.model_dump(), "importance": importance.get(f.name)} for f in known]
        return ModelInfo(
            name=name,
            version=version,
            algorithm=algorithm,
            algorithm_label=LABELS.get(algorithm, algorithm),
            run_id=mv.run_id or "",
            metrics=metrics,
            skill_vs_naive=skill,
            windows=windows,
            comparison=comparison,
            features=features,
        )

    def _comparison(self, test_window: str | None, champion: str) -> list[ComparisonRow]:
        """Baselines e candidatos do mesmo treino (mesma janela de teste), o run mais recente de cada um."""
        exp = mlflow.get_experiment_by_name(self._cfg.training.experiment)
        if exp is None or not test_window:
            return []
        runs = self._client.search_runs(
            [exp.experiment_id],
            filter_string=f"tags.test_window = '{test_window}'",
            order_by=["attributes.start_time DESC"],
            max_results=200,
        )
        rows: dict[str, ComparisonRow] = {}
        for run in runs:
            tags, metrics = run.data.tags, run.data.metrics
            match = RUN_NAME.match(tags.get("mlflow.runName", ""))
            if "mlflow.parentRunId" in tags or not match or "test_mae" not in metrics:
                continue  # trials aninhados e runs de outros tipos não entram no comparativo
            key = match["model"]
            kind: Literal["baseline", "candidate"] = "baseline" if tags.get("model_kind") == "baseline" else "candidate"
            rows.setdefault(
                key,
                ComparisonRow(
                    name=key,
                    label=LABELS.get(key, key),
                    kind=kind,
                    test_mae=float(metrics["test_mae"]),
                    champion=key == champion,
                ),
            )
        return sorted(rows.values(), key=lambda r: r.test_mae)
