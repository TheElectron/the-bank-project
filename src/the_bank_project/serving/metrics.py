"""Métricas Prometheus da API. Um registro por app, para os testes não compartilharem estado."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest, values

# Importar o Feast liga, como efeito colateral, o modo multiprocesso do prometheus_client (valores em arquivos
# compartilhados por nome). Aqui há um processo só e um registro por app, então voltamos aos valores em memória:
# sem isso, dois `ServingMetrics` somariam nos mesmos contadores.
values.ValueClass = values.MutexValue

LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
OUTFLOW_BUCKETS = (0, 500, 1_000, 2_500, 5_000, 10_000, 20_000, 50_000, 100_000, 300_000)


class ServingMetrics:
    """Contadores, histogramas e gauges expostos em `/metrics`."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.http_requests = Counter(
            "http_requests_total", "Requisições HTTP.", ["method", "path", "status"], registry=r
        )
        self.http_latency = Histogram(
            "http_request_duration_seconds", "Latência das requisições.", ["path"], buckets=LATENCY_BUCKETS, registry=r
        )
        self.predict_requests = Counter("predict_requests_total", "Chamadas de previsão.", ["mode"], registry=r)
        self.predictions = Counter("predictions_total", "Previsões geradas.", registry=r)
        self.accounts_not_found = Counter("predict_accounts_not_found_total", "Contas sem features.", registry=r)
        self.predicted_value = Histogram(
            "predicted_next_month_outflow", "Distribuição dos valores previstos.", buckets=OUTFLOW_BUCKETS, registry=r
        )
        self.model_info = Gauge(
            "model_info", "Campeão carregado (valor 1).", ["name", "version", "algorithm"], registry=r
        )
        self.model_loaded_at = Gauge(
            "model_loaded_timestamp_seconds", "Quando o campeão atual foi carregado.", registry=r
        )
        self._current: tuple[str, str, str] | None = None

    def set_model(self, name: str, version: str, algorithm: str, loaded_at: float) -> None:
        """Marca o campeão atual (zera as versões anteriores, para o Grafana ver só a vigente)."""
        if self._current is not None:
            self.model_info.remove(*self._current)
        self._current = (name, version, algorithm)
        self.model_info.labels(name=name, version=version, algorithm=algorithm).set(1)
        self.model_loaded_at.set(loaded_at)

    def render(self) -> bytes:
        return generate_latest(self.registry)
