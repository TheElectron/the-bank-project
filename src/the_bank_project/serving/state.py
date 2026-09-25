"""Estado compartilhado da API: dependências, montagem em produção e recarga do campeão."""

import asyncio
import logging
import time
from dataclasses import dataclass

import pandas as pd

from the_bank_project.config import GlobalConfig
from the_bank_project.features import FeatureReader
from the_bank_project.serving.catalog import AccountCatalog, load_catalog
from the_bank_project.serving.evaluation import EvaluationCache, build_report
from the_bank_project.serving.metrics import ServingMetrics
from the_bank_project.serving.model_store import ModelStore
from the_bank_project.serving.service import PredictionService
from the_bank_project.training.labels import LABELS_TABLE

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Dependências da API. Nos testes, entram versões falsas; em produção, `build_state`."""

    cfg: GlobalConfig
    service: PredictionService
    catalog: AccountCatalog
    models: ModelStore
    metrics: ServingMetrics
    evaluation: EvaluationCache


def build_state(cfg: GlobalConfig) -> AppState:
    """Abre a feature store, monta o catálogo e prepara o carregamento do campeão."""
    reader = FeatureReader(cfg.feast.repo)
    labels = pd.read_parquet(cfg.paths.gold / f"{LABELS_TABLE}.parquet")
    metrics = ServingMetrics()
    catalog = load_catalog(reader, labels, cfg.training.split)
    service = PredictionService(reader, catalog, metrics)
    return AppState(
        cfg=cfg,
        service=service,
        catalog=catalog,
        models=ModelStore(cfg, service.service_refs),
        metrics=metrics,
        evaluation=EvaluationCache(lambda bundle: build_report(reader, catalog, bundle, service.service_refs)),
    )


def refresh_champion(state: AppState) -> None:
    """Carrega o campeão se o alias mudou e, nesse caso, atualiza as métricas e dispara a avaliação no teste."""
    if state.models.refresh() and (bundle := state.models.bundle):
        info = bundle.info
        state.metrics.set_model(info.name, info.version, info.algorithm, time.time())
        state.evaluation.start(bundle)


async def poll_champion(state: AppState) -> None:
    """Consulta o alias `champion` de tempos em tempos e recarrega o modelo se a versão mudou."""
    while True:
        await asyncio.sleep(state.cfg.serving.model_poll_seconds)
        try:
            await asyncio.to_thread(refresh_champion, state)
        except Exception:
            logger.exception("Falha ao verificar o campeão.")
