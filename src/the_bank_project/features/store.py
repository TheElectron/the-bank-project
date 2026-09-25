"""Acesso à feature store. Nenhum outro módulo deve ler a Gold ou o Feast diretamente."""

import logging
import sys
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from feast import FeatureService, FeatureStore
from feast.repo_config import load_repo_config
from feast.repo_operations import apply_total

from the_bank_project.config import load_config

logger = logging.getLogger(__name__)

DEFAULT_SERVICE = "outflow_regression"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _repo(repo_path: Path | None) -> Path:
    return repo_path or load_config().feast.repo


def open_store(repo_path: Path | None = None) -> FeatureStore:
    """Abre a feature store do repositório (padrão: `feast.repo_path` da config)."""
    return FeatureStore(repo_path=str(_repo(repo_path)))


def apply_repo(repo_path: Path | None = None) -> None:
    """Registra entidade, views e services do repositório (equivale a `feast apply`; idempotente)."""
    path = _repo(repo_path).resolve()
    sys.path.insert(0, str(path))  # o Feast importa `features.py` do repositório, como a CLI dele faz
    try:
        apply_total(load_repo_config(path, path / "feature_store.yaml"), path, skip_source_validation=False)
    finally:
        sys.path.remove(str(path))
        sys.modules.pop("features", None)


def materialize_all(repo_path: Path | None = None, end_date: datetime | None = None) -> None:
    """Carrega no online store o valor mais recente de cada conta, a partir da Gold.

    Reprocessa o histórico inteiro (idempotente) em vez de `materialize_incremental`:
    o dataset é histórico (1993-1998), então a janela incremental, limitada pelo TTL a
    partir de "agora", não alcançaria nenhum dado.
    """
    end = end_date or datetime.now(UTC)
    logger.info("Materializando o online store até %s.", end.isoformat())
    open_store(repo_path).materialize(start_date=EPOCH, end_date=end)


class FeatureReader:
    """Leitor da feature store com o `FeatureStore` aberto uma vez (para o serving).

    O Feast usa SQLite e Dask por baixo; as chamadas são serializadas por um lock, então
    o mesmo leitor pode ser usado pelas threads do servidor web.
    """

    def __init__(self, repo_path: Path | None = None) -> None:
        self._store = open_store(repo_path)
        self._lock = threading.RLock()

    def service_features(self, service: str = DEFAULT_SERVICE) -> list[str]:
        """Referências `view:feature` de um FeatureService, na ordem em que ele as declara."""
        with self._lock:
            projections = self._store.get_feature_service(service).feature_view_projections
            return [f"{p.name}:{f.name}" for p in projections for f in p.features]

    def _refs(self, features: str | Sequence[str]) -> FeatureService | list[str]:
        return self._store.get_feature_service(features) if isinstance(features, str) else list(features)

    def offline(self, entity_df: pd.DataFrame, features: str | Sequence[str] = DEFAULT_SERVICE) -> pd.DataFrame:
        """Features com join point-in-time. Ver `get_offline_features`."""
        entity_df = entity_df.assign(account_id=entity_df["account_id"].astype("string"))  # mesmo dtype da Gold
        with self._lock:
            return self._store.get_historical_features(entity_df=entity_df, features=self._refs(features)).to_df()

    def online(self, account_ids: Sequence[str], features: str | Sequence[str] = DEFAULT_SERVICE) -> pd.DataFrame:
        """Features mais recentes de cada conta. Ver `get_online_features`."""
        rows = [{"account_id": a} for a in account_ids]
        with self._lock:
            return self._store.get_online_features(features=self._refs(features), entity_rows=rows).to_df()


def get_offline_features(
    entity_df: pd.DataFrame, features: str | Sequence[str] = DEFAULT_SERVICE, repo_path: Path | None = None
) -> pd.DataFrame:
    """Features para treino, com join point-in-time.

    Args:
        entity_df: colunas `account_id` e `event_timestamp` (uma linha por observação).
        features: nome de um FeatureService ou lista de referências `view:feature`.
        repo_path: repositório Feast (padrão: config).

    Returns:
        `entity_df` com as features vigentes em cada `event_timestamp`. Linhas sem nenhuma
            feature disponível naquele instante (conta ainda não aberta) não voltam. As
            views não têm TTL: depois do último mês ativo de uma conta, a feature vigente
            continua sendo a desse mês; monte o `entity_df` a partir de meses reais da Gold.
    """
    return FeatureReader(repo_path).offline(entity_df, features)


def get_online_features(
    account_ids: Sequence[str], features: str | Sequence[str] = DEFAULT_SERVICE, repo_path: Path | None = None
) -> pd.DataFrame:
    """Features mais recentes de cada conta, para serving. Conta desconhecida volta com nulos."""
    return FeatureReader(repo_path).online(account_ids, features)
