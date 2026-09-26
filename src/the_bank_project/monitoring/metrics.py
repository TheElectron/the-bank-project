"""Publica o resumo de drift no Prometheus via Pushgateway (o job é em lote: o Prometheus não o alcança por scrape).

Usa um coletor próprio em vez de `Gauge`: importar o Feast liga o modo multiprocesso do `prometheus_client`
(ver `serving/metrics.py`), e `Gauge` exigiria um diretório de valores compartilhados.
"""

import logging
from collections.abc import Iterator

from prometheus_client import CollectorRegistry, push_to_gateway
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from the_bank_project.monitoring.drift import DriftSummary

logger = logging.getLogger(__name__)

JOB = "drift"


class DriftCollector(Collector):
    """Expõe um `DriftSummary` como gauges (`drift_*`)."""

    def __init__(self, summary: DriftSummary) -> None:
        self.summary = summary

    def collect(self) -> Iterator[GaugeMetricFamily]:
        s = self.summary
        scalars = {
            "drift_detected": ("1 se o drift do dataset passou do limiar na última execução.", float(s.drift_detected)),
            "drift_share": ("Fração das features com drift.", s.drift_share),
            "drift_share_threshold": (
                "Fração de features com drift a partir da qual há drift.",
                s.drift_share_threshold,
            ),
            "drift_features_total": ("Features avaliadas.", float(s.n_features)),
            "drift_features_drifted": ("Features com drift.", float(s.n_drifted)),
            "drift_feature_threshold": ("Limiar de drift por feature (Wasserstein normalizada).", s.feature_threshold),
            "drift_current_rows": ("Linhas da janela atual.", float(s.current_rows)),
        }
        for name, (doc, value) in scalars.items():
            gauge = GaugeMetricFamily(name, doc)
            gauge.add_metric([], value)
            yield gauge
        scores = GaugeMetricFamily("drift_feature_score", "Score de drift por feature.", labels=["feature"])
        for feature, f in s.features.items():
            scores.add_metric([feature], f.score)
        yield scores
        if s.generated_at is not None:
            ts = GaugeMetricFamily("drift_report_timestamp_seconds", "Quando o relatório de drift foi gerado.")
            ts.add_metric([], s.generated_at.timestamp())
            yield ts


def push_drift(summary: DriftSummary, url: str, timeout: float = 10) -> None:
    """Envia o resumo ao Pushgateway, substituindo o grupo anterior (features removidas somem).

    Raises:
        OSError: se o Pushgateway não responder (`URLError` é subclasse).
    """
    registry = CollectorRegistry()
    registry.register(DriftCollector(summary))
    push_to_gateway(url, job=JOB, registry=registry, timeout=timeout)
    logger.info("Resumo de drift publicado em %s (job=%s).", url, JOB)
