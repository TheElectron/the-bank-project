import importlib.util
from types import ModuleType

import pandas as pd
import pytest
from feast import FeatureView
from feast.types import Bool, Float64, Int64, String, UnixTimestamp

from the_bank_project.config import PROJECT_ROOT
from the_bank_project.gold import build_gold

FEAST_TYPES = {"int64": Int64, "float64": Float64, "bool": Bool, "boolean": Bool}


def _load_definitions() -> ModuleType:
    spec = importlib.util.spec_from_file_location("feature_definitions", PROJECT_ROOT / "feature_repo" / "features.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_type(series: pd.Series):  # type: ignore[no-untyped-def]
    dtype = str(series.dtype).lower()
    if dtype.startswith("datetime64"):
        return UnixTimestamp
    if dtype in ("string", "str", "object"):
        return String
    return FEAST_TYPES[dtype]


@pytest.mark.parametrize(
    ("view", "table", "keys"),
    [
        ("account_static", "gold_account", {"account_id", "account_open_date"}),
        ("account_monthly", "gold_account_monthly_movements", {"account_id", "reference_month"}),
    ],
)
def test_feature_view_schema_matches_gold(silver: dict[str, pd.DataFrame], view: str, table: str, keys: set[str]):
    """Contrato de dados: mudou uma coluna da Gold, o schema do Feast precisa mudar junto."""
    fv: FeatureView = getattr(_load_definitions(), view)
    gold = build_gold(silver)[table]
    declared = {f.name: f.dtype for f in fv.schema}
    assert set(declared) == set(gold.columns) - keys
    for name, dtype in declared.items():
        assert dtype == _expected_type(gold[name]), f"{view}.{name}: {dtype} != {gold[name].dtype}"


def test_timestamp_fields_and_entity(silver: dict[str, pd.DataFrame]):
    defs = _load_definitions()
    assert defs.account_source.timestamp_field == "account_open_date"
    assert defs.monthly_source.timestamp_field == "reference_month"
    assert defs.account.join_key == "account_id"


def test_regression_service_has_only_monthly_features_and_no_target(silver: dict[str, pd.DataFrame]):
    defs = _load_definitions()
    projections = defs.outflow_regression.feature_view_projections
    assert [p.name for p in projections] == ["account_monthly"]
    names = {f.name for f in projections[0].features}
    assert {"outflow_3m_avg", "closing_balance", "previous_month_outflow"} <= names
    assert "next_month_outflow" not in names
    assert names <= {f.name for f in defs.account_monthly.schema}
