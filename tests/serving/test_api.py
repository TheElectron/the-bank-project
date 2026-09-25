import time
from collections.abc import Callable, Iterator

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from the_bank_project.serving.app import create_app
from the_bank_project.serving.feature_catalog import FEATURES
from the_bank_project.serving.schemas import PredictRequest
from the_bank_project.serving.state import AppState

FEATURE_NAMES = list(FEATURES)


def make_client(state: AppState) -> TestClient:
    return TestClient(create_app(state=state))


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    with make_client(state) as c:
        yield c


def predict(client: TestClient, **body: object) -> dict:  # type: ignore[type-arg]
    res = client.post("/predict", json=body)
    assert res.status_code == 200, res.text
    return res.json()  # type: ignore[no-any-return]


# --- contrato de entrada ---


def test_request_strips_and_deduplicates_ids():
    assert PredictRequest(account_ids=[" 1", "2", "1"]).account_ids == ["1", "2"]


@pytest.mark.parametrize("ids", [[], [""], ["1", "  "]])
def test_request_rejects_empty_or_blank_ids(ids: list[str]):
    with pytest.raises(ValidationError):
        PredictRequest(account_ids=ids)


# --- /predict ---


def test_predict_online_uses_the_latest_month_and_has_no_actual(client: TestClient):
    body = predict(client, account_ids=["3", "1"])
    assert [p["account_id"] for p in body["predictions"]] == ["3", "1"]  # ordem do pedido
    p = body["predictions"][0]
    assert p["features_as_of"] == "1998-08-31" and p["target_month"] == "1998-09-30"
    assert p["actual_next_month_outflow"] is None and p["error"] is None and p["split"] is None
    assert p["predicted_next_month_outflow"] > 0 and p["baseline_next_month_outflow"] > 0
    assert p["features"] is None and body["not_found"] == []
    assert body["model"] == {"name": "outflow_regression", "version": "1", "algorithm": "random_forest"}


def test_predict_online_prediction_is_the_model_applied_to_the_features(client: TestClient):
    body = predict(client, account_ids=["2"], include_features=True)
    p = body["predictions"][0]
    assert set(p["features"]) == set(FEATURE_NAMES)
    assert p["predicted_next_month_outflow"] == pytest.approx(0.9 * p["features"]["outflow_3m_avg"])


def test_predict_reports_unknown_accounts_without_failing_the_batch(client: TestClient):
    body = predict(client, account_ids=["1", "999", "2"])
    assert [p["account_id"] for p in body["predictions"]] == ["1", "2"] and body["not_found"] == ["999"]


def test_predict_historical_returns_actual_error_and_split(client: TestClient, state: AppState):
    month = pd.Timestamp("1998-07-31")
    body = predict(
        client, account_ids=["1", "2"], reference_month="1998-07-15", include_features=True
    )  # qualquer dia do mês
    p = body["predictions"][0]
    assert p["features_as_of"] == "1998-07-31" and p["target_month"] == "1998-08-31"
    assert p["actual_next_month_outflow"] == pytest.approx(state.catalog.actual("1", month))
    assert p["error"] == pytest.approx(p["predicted_next_month_outflow"] - p["actual_next_month_outflow"])
    assert p["split"] == state.catalog.split_of(month)


def test_predict_historical_features_are_those_of_the_reference_month(client: TestClient):
    early = predict(client, account_ids=["1"], reference_month="1997-06-30", include_features=True)["predictions"][0]
    late = predict(client, account_ids=["1"], reference_month="1998-07-31", include_features=True)["predictions"][0]
    assert early["features_as_of"] == "1997-06-30"
    assert early["features"]["outflow_3m_avg"] != late["features"]["outflow_3m_avg"]


def test_predict_unknown_month_is_404(client: TestClient):
    res = client.post("/predict", json={"account_ids": ["1"], "reference_month": "1970-01-31"})
    assert res.status_code == 404 and "1970-01-31" in res.json()["detail"]


def test_predict_month_without_actual_is_not_offered_as_historical(client: TestClient):
    # 1998-08 é o último mês com features, mas não tem valor real (T+1 não existe): só vale o modo online
    assert client.post("/predict", json={"account_ids": ["1"], "reference_month": "1998-08-31"}).status_code == 404


def test_predict_batch_limit_is_422(client: TestClient, state: AppState):
    ids = [str(i) for i in range(state.cfg.serving.max_batch + 1)]
    res = client.post("/predict", json={"account_ids": ids})
    assert res.status_code == 422 and str(state.cfg.serving.max_batch) in res.json()["detail"]


def test_predict_never_returns_negative_outflow(state_factory: Callable[..., AppState]):
    with make_client(state_factory(fixed=-500.0)) as c:
        assert predict(c, account_ids=["1"])["predictions"][0]["predicted_next_month_outflow"] == 0.0


def test_predict_without_champion_is_503_and_health_says_so(state_factory: Callable[..., AppState]):
    with make_client(state_factory(with_model=False)) as c:
        assert c.post("/predict", json={"account_ids": ["1"]}).status_code == 503
        res = c.get("/health")
        assert res.status_code == 503 and res.json()["status"] == "sem_modelo"
        assert c.get("/api/model").status_code == 503


def test_model_feature_store_mismatch_is_503(state_factory: Callable[..., AppState]):
    with make_client(state_factory(input_names=[*FEATURE_NAMES, "feature_inexistente"])) as c:
        res = c.post("/predict", json={"account_ids": ["1"]})
        assert res.status_code == 503 and "feature_inexistente" in res.json()["detail"]


# --- operação ---


def test_health_reports_model_and_catalog(client: TestClient):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["model"]["version"] == "1" and body["accounts"] == 12
    assert body["latest_month"] == "1998-08-31"


def test_metrics_expose_prometheus_counters_and_model_info(client: TestClient):
    predict(client, account_ids=["1", "2", "999"])
    text = client.get("/metrics").text
    assert "predictions_total 2.0" in text and "predict_accounts_not_found_total 1.0" in text
    assert 'predict_requests_total{mode="online"} 1.0' in text
    assert 'model_info{algorithm="random_forest",name="outflow_regression",version="1"} 1.0' in text
    assert 'http_requests_total{method="POST",path="/predict",status="200"} 1.0' in text
    assert "predicted_next_month_outflow_bucket" in text


def test_metrics_label_by_route_template_not_by_raw_path(client: TestClient):
    client.get("/api/accounts/1")
    client.get("/api/accounts/2")
    assert 'path="/api/accounts/{account_id}",status="200"} 2.0' in client.get("/metrics").text


# --- apoio à interface ---


def test_months_start_with_latest_then_history_with_splits(client: TestClient):
    months = client.get("/api/months").json()
    assert months[0]["reference_month"] is None and months[0]["has_actual"] is False
    history = months[1:]
    assert [m["reference_month"] for m in history] == sorted((m["reference_month"] for m in history), reverse=True)
    splits = [m["split"] for m in reversed(history)]
    assert splits[0] == "treino" and splits[-1] == "teste" and set(splits) == {"treino", "validacao", "teste", "folga"}
    assert all(m["n_accounts"] == 12 for m in history)


def test_accounts_search_and_pagination(client: TestClient):
    page = client.get("/api/accounts", params={"search": "1", "limit": 2}).json()
    assert page["total"] == 4 and [a["account_id"] for a in page["items"]] == ["1", "10"]  # 1, 10, 11, 12
    rest = client.get("/api/accounts", params={"search": "1", "limit": 5, "offset": 2}).json()
    assert [a["account_id"] for a in rest["items"]] == ["11", "12"]
    info = page["items"][0]
    assert info["district_name"] and info["owner_gender"] in {"F", "M"} and info["first_month"] and info["last_month"]


def test_accounts_are_ordered_by_numeric_id_and_filtered_by_month(client: TestClient):
    ids = [a["account_id"] for a in client.get("/api/accounts", params={"limit": 12}).json()["items"]]
    assert ids == [str(i) for i in range(1, 13)]
    assert client.get("/api/accounts", params={"reference_month": "1990-01-31"}).json()["total"] == 0


def test_sample_is_reproducible_with_a_seed_and_respects_n(client: TestClient):
    params = {"n": 4, "seed": 7, "reference_month": "1998-01-31"}
    first = client.get("/api/accounts/sample", params=params).json()
    assert len(first) == 4 and first == client.get("/api/accounts/sample", params=params).json()
    assert len({a["account_id"] for a in first}) == 4
    assert client.get("/api/accounts/sample", params={"n": 50}).json().__len__() == 12  # não passa do disponível


def test_account_detail_and_404(client: TestClient):
    assert client.get("/api/accounts/5").json()["account_id"] == "5"
    assert client.get("/api/accounts/999").status_code == 404


def test_history_returns_ordered_months_and_the_actual_next_value(client: TestClient, state: AppState):
    body = client.get("/api/accounts/1/history", params={"reference_month": "1998-07-31", "months": 6}).json()
    months = [p["month"] for p in body["points"]]
    assert months == ["1998-02-28", "1998-03-31", "1998-04-30", "1998-05-31", "1998-06-30", "1998-07-31"]
    assert body["actual_next_month_outflow"] == pytest.approx(state.catalog.actual("1", pd.Timestamp("1998-07-31")))
    assert all(p["outflow"] is not None for p in body["points"])
    assert client.get("/api/accounts/999/history", params={"reference_month": "1998-07-31"}).status_code == 404


def test_model_endpoint_lists_features_with_labels(client: TestClient):
    body = client.get("/api/model").json()
    assert body["version"] == "1" and {f["name"] for f in body["features"]} == set(FEATURE_NAMES)
    assert all(f["label"] and f["group"] and f["unit"] for f in body["features"])


def test_evaluation_is_computed_in_background_and_matches_a_manual_calculation(client: TestClient, state: AppState):
    deadline = time.time() + 20
    while time.time() < deadline:
        res = client.get("/api/evaluation").json()
        if res["ready"]:
            break
        time.sleep(0.1)
    assert res["ready"], "relatório de avaliação não ficou pronto"
    report = res["report"]
    pairs = state.catalog.pairs("teste")
    assert report["n_rows"] == len(pairs) and len(report["by_month"]) == pairs["event_timestamp"].nunique()
    assert 0 <= report["win_rate"] <= 1 and report["model"]["mae"] > 0 and report["axis_max"] > 0
    assert len(report["points"]) == min(1200, len(pairs))


# --- interface web ---


def test_index_and_static_assets_are_served(client: TestClient):
    page = client.get("/")
    assert page.status_code == 200 and "The Bank Project" in page.text and "/static/js/app.js" in page.text
    for path in ("/static/styles.css", "/static/js/app.js", "/static/js/charts.js", "/static/fonts/fraunces.woff2"):
        assert client.get(path).status_code == 200, path
    assert client.get("/docs").status_code == 200  # OpenAPI
