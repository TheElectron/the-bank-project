"""Publicação do resumo de drift: conteúdo das métricas, push HTTP e CLI."""

import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from the_bank_project.monitoring import DriftCollector, DriftSummary, FeatureDrift, load_summary, push_drift
from the_bank_project.monitoring import cli as monitoring_cli

GENERATED_AT = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def make_summary(detected: bool = True) -> DriftSummary:
    return DriftSummary(
        reference_window="1993-01-31..1998-06-30", current_window="1998-09-30..1998-11-30",
        reference_rows=1000, current_rows=300, n_features=2, n_drifted=1, drift_share=0.5,
        drift_detected=detected, feature_threshold=0.1, drift_share_threshold=0.5,
        features={"a": FeatureDrift(score=0.4, drifted=True), "b": FeatureDrift(score=0.02, drifted=False)},
        generated_at=GENERATED_AT,
    )  # fmt: skip


def render(summary: DriftSummary) -> str:
    registry = CollectorRegistry()
    registry.register(DriftCollector(summary))
    return generate_latest(registry).decode()


def test_collector_exposes_summary_as_gauges() -> None:
    text = render(make_summary())
    assert "drift_detected 1.0" in text
    assert "drift_share 0.5" in text
    assert "drift_features_drifted 1.0" in text
    assert 'drift_feature_score{feature="a"} 0.4' in text
    assert 'drift_feature_score{feature="b"} 0.02' in text
    line = next(x for x in text.splitlines() if x.startswith("drift_report_timestamp_seconds "))
    assert float(line.split()[1]) == pytest.approx(GENERATED_AT.timestamp())  # o texto sai em notação científica


def test_collector_reports_zero_when_no_drift_and_skips_missing_timestamp() -> None:
    text = render(make_summary(detected=False).model_copy(update={"generated_at": None}))
    assert "drift_detected 0.0" in text
    assert "drift_report_timestamp_seconds" not in text


class FakePushgateway:
    """Servidor HTTP mínimo que guarda o último `PUT`/`POST` recebido."""

    def __init__(self) -> None:
        outer = self
        self.requests: list[tuple[str, str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                outer.requests.append((self.command, self.path, body))
                self.send_response(200)
                self.end_headers()

            do_POST = do_PUT

            def log_message(self, *_: object) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FakePushgateway":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_push_drift_replaces_the_drift_group() -> None:
    with FakePushgateway() as gw:
        push_drift(make_summary(), gw.url)
    method, path, body = gw.requests[0]
    assert method == "PUT"  # substitui o grupo: features que sumiram não ficam órfãs
    assert path == "/metrics/job/drift"
    assert 'drift_feature_score{feature="a"} 0.4' in body


def test_push_drift_raises_when_gateway_is_down() -> None:
    with pytest.raises(OSError):
        push_drift(make_summary(), "http://127.0.0.1:1", timeout=1)


def test_load_summary_roundtrip_and_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="make drift"):
        load_summary(tmp_path)
    (tmp_path / "drift_summary.json").write_text(make_summary().model_dump_json())
    assert load_summary(tmp_path) == make_summary()


def test_cli_push_publishes_the_saved_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[DriftSummary, str]] = []
    monkeypatch.setenv("PUSHGATEWAY_URL", "http://gw:9091")
    monkeypatch.setattr(monitoring_cli, "load_summary", lambda _: make_summary())
    monkeypatch.setattr(monitoring_cli, "push_drift", lambda s, url, **_: sent.append((s, url)))
    assert monitoring_cli.main(["push"]) == 0
    assert sent == [(make_summary(), "http://gw:9091")]


def test_cli_push_without_url_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    monkeypatch.setattr(monitoring_cli, "Settings", lambda: type("S", (), {"pushgateway_url": None})())
    monkeypatch.setattr(monitoring_cli, "load_summary", lambda _: make_summary())
    assert monitoring_cli.main(["push"]) == 1


def test_cli_drift_reports_and_skips_push_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(monitoring_cli, "Settings", lambda: type("S", (), {"pushgateway_url": None})())
    monkeypatch.setattr(monitoring_cli, "run_drift", lambda cfg: calls.append("drift") or make_summary())
    monkeypatch.setattr(monitoring_cli, "push_drift", lambda s, url: calls.append("push"))
    assert monitoring_cli.main(["drift"]) == 0
    assert calls == ["drift"]
