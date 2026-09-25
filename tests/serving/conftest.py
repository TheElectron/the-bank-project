"""Estado sintético da API: Feast e modelo falsos, catálogo e serviço reais."""

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
import pytest

from the_bank_project.config import GlobalConfig, ServingConfig
from the_bank_project.serving.catalog import AccountCatalog
from the_bank_project.serving.evaluation import EvaluationCache, build_report
from the_bank_project.serving.feature_catalog import FEATURES
from the_bank_project.serving.metrics import ServingMetrics
from the_bank_project.serving.model_store import ModelBundle
from the_bank_project.serving.schemas import ModelInfo
from the_bank_project.serving.service import PredictionService
from the_bank_project.serving.state import AppState

N_ACCOUNTS, N_MONTHS = 12, 20
FEATURE_NAMES = list(FEATURES)
REFS = [f"account_monthly:{n}" for n in FEATURE_NAMES]
STATIC = pd.DataFrame({
    "account_id": [str(i) for i in range(1, N_ACCOUNTS + 1)],
    "district_name": [f"Distrito {i % 3}" for i in range(N_ACCOUNTS)],
    "district_region": ["Prague"] * N_ACCOUNTS,
    "owner_gender": ["F", "M"] * (N_ACCOUNTS // 2),
    "account_frequency": ["MENSAL"] * N_ACCOUNTS,
    "has_loan": [i % 4 == 0 for i in range(N_ACCOUNTS)],
    "has_card": [i % 3 == 0 for i in range(N_ACCOUNTS)],
    "dependent_count": [i % 2 for i in range(N_ACCOUNTS)],
})  # fmt: skip


def make_monthly() -> pd.DataFrame:
    """12 contas x 20 meses (1997-01 .. 1998-08) com as 29 features do serviço + year/month."""
    rng = np.random.default_rng(3)
    months = pd.date_range("1997-01-31", periods=N_MONTHS, freq="ME")
    rows = []
    for m in months:
        for acc in range(1, N_ACCOUNTS + 1):
            row = {name: float(rng.uniform(100, 20_000)) for name in FEATURE_NAMES}
            row.update(account_id=str(acc), month_end=m, year=float(m.year), month=float(m.month))
            rows.append(row)
    return pd.DataFrame(rows)


class FakeReader:
    """Mesma interface do `FeatureReader`, sobre um DataFrame em memória."""

    def __init__(self, monthly: pd.DataFrame) -> None:
        self.monthly = monthly

    def service_features(self, service: str = "outflow_regression") -> list[str]:
        return list(REFS)

    def online(self, account_ids: Sequence[str], features: object = None) -> pd.DataFrame:
        refs = list(features) if isinstance(features, list) else REFS
        cols = [r.split(":", 1)[1] for r in refs]
        if all(c in STATIC.columns for c in cols):
            out = STATIC.set_index("account_id").reindex(list(account_ids))[cols].reset_index()
            return out.rename(columns={"index": "account_id"})
        latest = self.monthly.sort_values("month_end").groupby("account_id").tail(1).set_index("account_id")
        out = latest.reindex(list(account_ids))[cols].reset_index()
        return out.rename(columns={"index": "account_id"})

    def offline(self, entity_df: pd.DataFrame, features: object = None) -> pd.DataFrame:
        refs = list(features) if isinstance(features, list) else REFS
        cols = [r.split(":", 1)[1] for r in refs]
        ent = entity_df.assign(account_id=entity_df["account_id"].astype(str))
        ent = ent.assign(ts=pd.to_datetime(ent["event_timestamp"]).dt.tz_localize(None))
        out = []
        for _, e in ent.iterrows():
            rows = self.monthly[
                (self.monthly["account_id"] == e["account_id"]) & (self.monthly["month_end"] <= e["ts"])
            ]
            if len(rows):
                latest = rows.sort_values("month_end").iloc[-1]
                out.append(
                    {
                        "account_id": e["account_id"],
                        "event_timestamp": e["event_timestamp"],
                        **{c: latest[c] for c in cols},
                    }
                )
        return pd.DataFrame(out)


class FakeModel:
    """Prevê 0,9 x a média de saídas de 3 meses (ou um valor fixo, para testar o corte em zero)."""

    def __init__(self, fixed: float | None = None) -> None:
        self.fixed = fixed

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.fixed is not None:
            return np.full(len(X), self.fixed)
        return 0.9 * X["outflow_3m_avg"].to_numpy()


def make_info(version: str = "1") -> ModelInfo:
    return ModelInfo(
        name="outflow_regression", version=version, algorithm="random_forest", algorithm_label="Random Forest",
        run_id="r1", metrics={"test_mae": 100.0}, skill_vs_naive=0.2, windows={"test_window": "x"},
        comparison=[], features=[{**FEATURES[n].model_dump(), "importance": None} for n in FEATURE_NAMES],
    )  # fmt: skip


class FakeModels:
    """`ModelStore` de mentira: o campeão é carregado na primeira `refresh`."""

    def __init__(self, bundle: ModelBundle | None) -> None:
        self._pending, self.bundle = bundle, None

    def refresh(self) -> bool:
        if self._pending is None or self.bundle is not None:
            return False
        self.bundle = self._pending
        return True


def make_state(
    *, fixed: float | None = None, with_model: bool = True, input_names: list[str] | None = None
) -> AppState:
    monthly = make_monthly()
    reader = FakeReader(monthly)
    ordered = monthly.sort_values(["account_id", "month_end"])
    label = ordered.groupby("account_id")["outflow_amount"].shift(-1)
    labels = ordered.assign(next_month_outflow=label).dropna(subset=["next_month_outflow"])
    labels = labels.rename(columns={"month_end": "event_timestamp"})[
        ["account_id", "event_timestamp", "next_month_outflow"]
    ]
    cfg = GlobalConfig.model_validate(
        {"kaggle": {"dataset": "o/d"}, "serving": ServingConfig(model_poll_seconds=0).model_dump()}
    )
    catalog = AccountCatalog(labels, STATIC, cfg.training.split)
    metrics = ServingMetrics()
    service = PredictionService(reader, catalog, metrics)  # type: ignore[arg-type]
    bundle = ModelBundle(FakeModel(fixed), input_names or FEATURE_NAMES, make_info()) if with_model else None
    return AppState(
        cfg=cfg, service=service, catalog=catalog, models=FakeModels(bundle),  # type: ignore[arg-type]
        metrics=metrics,
        evaluation=EvaluationCache(lambda b: build_report(reader, catalog, b, REFS)),  # type: ignore[arg-type]
    )  # fmt: skip


@pytest.fixture
def state_factory() -> Callable[..., AppState]:
    return make_state


@pytest.fixture
def state() -> AppState:
    return make_state()
