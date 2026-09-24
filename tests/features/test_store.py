from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from the_bank_project.features import apply_repo, cli, get_offline_features, get_online_features, materialize_all

FEATURES = ["account_monthly:closing_balance", "account_monthly:outflow_amount", "account_static:owner_gender"]


def _entities(*rows: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"account_id": [a for a, _ in rows], "event_timestamp": pd.to_datetime([t for _, t in rows], utc=True)}
    )


@pytest.fixture
def applied(repo: Path) -> Path:
    apply_repo(repo)
    return repo


def test_offline_features_are_point_in_time(applied: Path):
    entities = _entities(("1", "1993-02-15"), ("1", "1993-03-30"), ("1", "1993-03-31"), ("1", "1993-04-05"))
    df = get_offline_features(entities, FEATURES, applied).set_index("event_timestamp")
    at = lambda ts: df.loc[pd.Timestamp(ts, tz="UTC")]  # noqa: E731
    assert at("1993-02-15")["closing_balance"] == 700  # só janeiro estava fechado
    assert at("1993-03-30")["closing_balance"] == 700  # março só vale a partir de 03-31: sem vazamento
    assert at("1993-03-31")["closing_balance"] == 1200
    assert at("1993-04-05")["closing_balance"] == 1200
    assert df["owner_gender"].eq("F").all()


def test_offline_features_have_no_ttl_so_the_latest_closed_month_stays_current(applied: Path):
    """Documenta o comportamento sem TTL (ver comentário em feature_repo/features.py)."""
    df = get_offline_features(_entities(("1", "1993-06-30")), FEATURES, applied)
    assert df["closing_balance"].iloc[0] == 1200 and df["owner_gender"].iloc[0] == "F"


def test_offline_drops_rows_before_the_account_exists(applied: Path):
    df = get_offline_features(_entities(("2", "1993-01-15"), ("2", "1993-02-28")), FEATURES, applied)
    assert df["event_timestamp"].tolist() == [pd.Timestamp("1993-02-28", tz="UTC")]  # conta 2 abre em fev/93


def test_offline_accepts_feature_service_name(applied: Path):
    df = get_offline_features(_entities(("1", "1993-03-31")), "outflow_regression", applied)
    assert {"outflow_3m_avg", "closing_balance"} <= set(df.columns) and "owner_gender" not in df.columns


def test_online_features_return_latest_month_and_nulls_for_unknown_accounts(applied: Path):
    materialize_all(applied, end_date=datetime(2030, 1, 1, tzinfo=UTC))
    df = get_online_features(["1", "2", "999"], FEATURES, applied).set_index("account_id")
    assert df.loc["1", "closing_balance"] == 1200 and df.loc["1", "owner_gender"] == "F"  # mar/93, o mais recente
    assert df.loc["2", "closing_balance"] == 50 and df.loc["2", "owner_gender"] == "M"
    assert df.loc["999"].isna().all()


def test_materialize_is_idempotent(applied: Path):
    for _ in range(2):
        materialize_all(applied, end_date=datetime(2030, 1, 1, tzinfo=UTC))
    df = get_online_features(["1"], FEATURES, applied)
    assert len(df) == 1 and df["closing_balance"].iloc[0] == 1200


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "apply_repo", lambda: calls.append("apply"))
    monkeypatch.setattr(cli, "materialize_all", lambda: calls.append("materialize"))
    return calls


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ("apply", ["apply"]),
        ("materialize", ["materialize"]),
        ("all", ["apply", "materialize"]),
        (None, ["apply", "materialize"]),
    ],
)
def test_cli_runs_requested_steps(calls: list[str], step: str | None, expected: list[str]):
    assert cli.main([step] if step else []) == 0
    assert calls == expected


def test_cli_returns_1_on_error(calls: list[str], monkeypatch: pytest.MonkeyPatch):
    def boom() -> None:
        raise RuntimeError("falhou")

    monkeypatch.setattr(cli, "apply_repo", boom)
    assert cli.main(["apply"]) == 1
