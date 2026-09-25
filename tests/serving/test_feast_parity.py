"""Serving com o Feast de verdade: online x offline devem dar a mesma previsão."""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from the_bank_project.config import SplitConfig
from the_bank_project.features import FeatureReader, apply_repo, materialize_all
from the_bank_project.serving.catalog import AccountCatalog, load_catalog
from the_bank_project.serving.feature_catalog import FEATURES
from the_bank_project.serving.metrics import ServingMetrics
from the_bank_project.serving.model_store import ModelBundle
from the_bank_project.serving.schemas import ModelInfo
from the_bank_project.serving.service import PredictionService


class HalfMean3m:
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X["outflow_3m_avg"].to_numpy() * 0.5 + X["closing_balance"].to_numpy() * 0.01


@pytest.fixture
def parts(repo: Path) -> tuple[FeatureReader, AccountCatalog, PredictionService, ModelBundle]:
    apply_repo(repo)
    materialize_all(repo, end_date=datetime(2030, 1, 1, tzinfo=UTC))
    reader = FeatureReader(repo)
    months = pd.date_range("1993-01-31", periods=14, freq="ME")  # meses só para o catálogo (a Gold sintética tem 3)
    labels = pd.DataFrame(
        [(a, m, 100.0 + i) for a in ("1", "2") for i, m in enumerate(months)],
        columns=["account_id", "event_timestamp", "next_month_outflow"],
    )
    catalog = load_catalog(reader, labels, SplitConfig())
    service = PredictionService(reader, catalog, ServingMetrics())
    info = ModelInfo(
        name="m",
        version="1",
        algorithm="x",
        algorithm_label="X",
        run_id="",
        metrics={},
        skill_vs_naive=None,
        windows={},
        comparison=[],
        features=[],
    )
    names = [r.split(":", 1)[1] for r in service.service_refs]
    return reader, catalog, service, ModelBundle(HalfMean3m(), names, info)


def test_service_features_are_exactly_the_documented_catalog(parts):  # type: ignore[no-untyped-def]
    reader, _, service, _ = parts
    assert {r.split(":", 1)[1] for r in service.service_refs} == set(
        FEATURES
    )  # todo feature do modelo tem nome legível


def test_online_and_offline_predictions_are_identical_for_the_same_month(parts):  # type: ignore[no-untyped-def]
    _, _, service, bundle = parts
    online = service.predict(bundle, ["1", "2"], None, include_features=True)
    by_id = {p.account_id: p for p in online.predictions}
    assert (
        str(by_id["1"].features_as_of) == "1993-03-31" and str(by_id["2"].features_as_of) == "1993-02-28"
    )  # último mês de cada conta
    offline = service.predict(bundle, ["1"], pd.Timestamp("1993-03-31"), include_features=True).predictions[0]
    assert offline.predicted_next_month_outflow == pytest.approx(by_id["1"].predicted_next_month_outflow)
    assert offline.features == by_id["1"].features  # mesmas features nos dois caminhos: sem skew treino/serving


def test_offline_prediction_uses_only_the_month_asked(parts):  # type: ignore[no-untyped-def]
    _, _, service, bundle = parts
    jan = service.predict(bundle, ["1"], pd.Timestamp("1993-01-31"), include_features=True).predictions[0]
    mar = service.predict(bundle, ["1"], pd.Timestamp("1993-03-31"), include_features=True).predictions[0]
    assert jan.features["closing_balance"] == 700.0 and mar.features["closing_balance"] == 1200.0  # type: ignore[index]
    assert jan.actual_next_month_outflow == 100.0 and jan.error == pytest.approx(
        jan.predicted_next_month_outflow - 100.0
    )


def test_history_comes_from_the_offline_store(parts):  # type: ignore[no-untyped-def]
    _, _, service, _ = parts
    history = service.history("1", pd.Timestamp("1993-03-31"), 3)
    assert [str(p.month) for p in history.points] == ["1993-01-31", "1993-02-28", "1993-03-31"]
    assert [p.outflow for p in history.points] == [300.0, 0.0, 200.0]  # jan, fev (sem movimento), mar
    assert history.actual_next_month_outflow == 102.0


def test_catalog_static_attributes_come_from_feast(parts):  # type: ignore[no-untyped-def]
    _, catalog, _, _ = parts
    info = catalog.info("1")
    assert (
        info
        and info.district_name == "Praha"
        and info.owner_gender == "F"
        and info.has_loan is True
        and info.has_card is True
    )
    assert info.dependent_count == 1
