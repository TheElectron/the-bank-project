"""Contrato dos arquivos de monitoramento: os nomes de métricas usados existem em `ServingMetrics`."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from the_bank_project.monitoring import DriftCollector, DriftSummary, FeatureDrift
from the_bank_project.serving.metrics import ServingMetrics

MONITORING = Path(__file__).resolve().parents[2] / "monitoring"
SUFFIXES = {"counter": ["_total"], "histogram": ["_bucket", "_count", "_sum"], "gauge": [""]}
NOT_METRICS = {"histogram_quantile"}
TOKEN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|\bup\b")


def exposed_names() -> set[str]:
    """Nomes de série que a API e o job de drift expõem (inclui os sufixos `_total`, `_bucket`...)."""
    summary = DriftSummary(
        reference_window="", current_window="", reference_rows=1, current_rows=1, n_features=1, n_drifted=0,
        drift_share=0, drift_detected=False, feature_threshold=0.1, drift_share_threshold=0.5,
        features={"a": FeatureDrift(score=0, drifted=False)}, generated_at=datetime.now(UTC),
    )  # fmt: skip
    families = [*ServingMetrics().registry.collect(), *DriftCollector(summary).collect()]
    return {f.name + s for f in families for s in SUFFIXES.get(f.type, [""])} | {"up"}


def metric_names(expr: str) -> set[str]:
    """Identificadores com `_` (ou `up`) da expressão PromQL, sem os labels entre `{}` nem as funções conhecidas."""
    expr = re.sub(r"\{[^}]*\}", "", expr)
    return {t for t in TOKEN.findall(expr) if t not in NOT_METRICS}


def dashboard_exprs() -> list[str]:
    dash = json.loads((MONITORING / "grafana/dashboards/serving.json").read_text())
    return [t["expr"] for p in dash["panels"] for t in p.get("targets", [])]


def alert_rules() -> list[dict[str, Any]]:
    groups = yaml.safe_load((MONITORING / "alerts.yml").read_text())["groups"]
    return [r for g in groups for r in g["rules"]]


def test_prometheus_scrapes_serving() -> None:
    cfg = yaml.safe_load((MONITORING / "prometheus.yml").read_text())
    job = next(j for j in cfg["scrape_configs"] if j["job_name"] == "serving")
    assert job["metrics_path"] == "/metrics"
    assert job["static_configs"][0]["targets"] == ["serving:8000"]


@pytest.mark.parametrize("rule", alert_rules(), ids=lambda r: r["alert"])
def test_alert_uses_exposed_metrics(rule: dict[str, Any]) -> None:
    assert metric_names(rule["expr"]) <= exposed_names()
    assert rule["annotations"]["summary"] and rule["labels"]["severity"]


@pytest.mark.parametrize("expr", dashboard_exprs())
def test_dashboard_uses_exposed_metrics(expr: str) -> None:
    assert metric_names(expr) <= exposed_names()


def test_dashboard_panels_have_unique_ids() -> None:
    dash = json.loads((MONITORING / "grafana/dashboards/serving.json").read_text())
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids))
    assert dash["uid"] == "serving-overview"


def test_pushgateway_is_scraped_honoring_labels() -> None:
    cfg = yaml.safe_load((MONITORING / "prometheus.yml").read_text())
    job = next(j for j in cfg["scrape_configs"] if j["job_name"] == "pushgateway")
    assert job["honor_labels"] is True  # senão o job "drift" do push vira o do próprio Pushgateway
    assert job["static_configs"][0]["targets"] == ["pushgateway:9091"]


def test_datasource_uid_matches_dashboard() -> None:
    ds = yaml.safe_load((MONITORING / "grafana/provisioning/datasources/prometheus.yml").read_text())
    dash = (MONITORING / "grafana/dashboards/serving.json").read_text()
    assert f'"uid": "{ds["datasources"][0]["uid"]}"' in dash
