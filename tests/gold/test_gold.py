from pathlib import Path

import pandas as pd
import pytest

from the_bank_project.gold import GoldQualityError, build_gold, check_gold, silver_to_gold
from the_bank_project.gold.transform import GOLD_TABLES, SILVER_TABLES
from the_bank_project.io import write_parquet_atomic

D = pd.Timestamp


def monthly(silver: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return build_gold(silver)["gold_account_monthly_movements"].set_index(["account_id", "reference_month"])


# --- gold_account ---


def test_gold_account_has_one_row_per_account_with_owner_and_district(silver: dict[str, pd.DataFrame]):
    a = build_gold(silver)["gold_account"].set_index("account_id")
    assert list(a.index) == ["1", "2"] and a.index.is_unique
    assert (a.loc["1", "owner_client_id"], a.loc["1", "owner_gender"]) == ("10", "F")  # o titular, não o dependente
    assert a.loc["1", "owner_district_id"] == "2" and a.loc["1", "district_id"] == "1"
    assert a.loc["1", "district_name"] == "Praha" and a.loc["1", "district_average_salary"] == 12000
    assert a["dependent_count"].to_dict() == {"1": 1, "2": 0}


def test_gold_account_card_and_loan_flags(silver: dict[str, pd.DataFrame]):
    a = build_gold(silver)["gold_account"].set_index("account_id")
    assert a["has_card"].to_dict() == {"1": True, "2": False} and a.loc["1", "card_type"] == "gold"
    assert a["has_loan"].to_dict() == {"1": True, "2": False}
    assert a.loc["1", "loan_payment_ratio"] == pytest.approx(1000 / 12000)
    assert a.loc["2", ["loan_amount", "loan_payment_ratio", "loan_status"]].isna().all()


# --- gold_account_monthly_movements ---


def test_monthly_fills_gap_months_between_first_and_last(silver: dict[str, pd.DataFrame]):
    m = monthly(silver)
    assert [str(x[1].date()) for x in m.index if x[0] == "1"] == ["1993-01-31", "1993-02-28", "1993-03-31"]
    feb = m.loc[("1", D("1993-02-28"))]
    assert feb["transaction_count"] == 0 and feb["inflow_amount"] == 0 and feb["active_days"] == 0
    assert feb["opening_balance"] == feb["closing_balance"] == feb["avg_balance"] == 700  # saldo carregado
    assert pd.isna(feb["avg_transaction_amount"])
    assert len(m.loc["2"]) == 1  # conta 2 só tem fevereiro: sem preenchimento antes/depois


def test_monthly_aggregates_amounts_counts_and_rules(silver: dict[str, pd.DataFrame]):
    m = monthly(silver)
    jan, mar = m.loc[("1", D("1993-01-31"))], m.loc[("1", D("1993-03-31"))]
    assert (jan["transaction_count"], jan["active_days"], jan["inflow_amount"], jan["outflow_amount"]) == (
        2,
        2,
        1000,
        300,
    )
    assert jan["debit_transaction_count"] == 1 and jan["withdrawal_transaction_count"] == 1  # SAQUE conta como saída
    assert jan["cash_withdrawal_amount"] == 300 and jan["cash_withdrawal_count"] == 1
    assert (jan["min_transaction_amount"], jan["max_transaction_amount"]) == (300, 1000)
    assert (mar["transaction_count"], mar["active_days"], mar["net_flow"]) == (2, 1, 500)
    assert (
        mar["transfer_transaction_count"] == 2
        and mar["transfer_out_amount"] == 200
        and mar["transfer_in_amount"] == 700
    )
    assert mar["loan_payment_amount"] == 200 and mar["loan_payment_count"] == 1
    assert "leasing_payment_amount" not in m.columns


def test_monthly_balances_resolve_same_day_order_despite_trans_id(silver: dict[str, pd.DataFrame]):
    m = monthly(silver)
    jan, mar = m.loc[("1", D("1993-01-31"))], m.loc[("1", D("1993-03-31"))]
    assert (jan["opening_balance"], jan["closing_balance"]) == (0, 700)
    assert (mar["opening_balance"], mar["closing_balance"]) == (700, 1200)  # por `trans_id` daria 500 no fim
    assert (mar["min_balance"], mar["max_balance"]) == (500, 1200)


def test_monthly_window_features(silver: dict[str, pd.DataFrame]):
    m = monthly(silver)
    jan, feb, mar = (m.loc[("1", D(f"1993-{x}"))] for x in ("01-31", "02-28", "03-31"))
    assert (
        pd.isna(jan["previous_month_outflow"])
        and feb["previous_month_outflow"] == 300
        and mar["previous_month_outflow"] == 0
    )
    assert jan["outflow_3m_avg"] == 300  # janela incompleta usa o que existe
    assert (mar["outflow_3m_sum"], mar["outflow_3m_avg"]) == (500, pytest.approx(500 / 3))
    assert mar["inflow_3m_avg"] == pytest.approx(1700 / 3)
    assert feb["outflow_mom_change"] == -1 and pd.isna(mar["outflow_mom_change"])  # base 0 -> nulo, não inf
    assert mar["balance_mom_change"] == 500 and pd.isna(jan["balance_mom_change"])


def test_monthly_calendar_columns_and_account_age(silver: dict[str, pd.DataFrame]):
    m = monthly(silver)
    mar = m.loc[("1", D("1993-03-31"))]
    assert (mar["year"], mar["month"], mar["account_age_months"]) == (1993, 3, 2)
    assert m.loc[("2", D("1993-02-28")), "account_age_months"] == 0  # aberta em fev/93


def test_window_features_never_use_future_months(silver: dict[str, pd.DataFrame]):
    """Anti-vazamento: mudar um mês futuro não pode alterar nenhuma feature de meses anteriores."""
    base = monthly(silver)
    changed = {**silver, "trans": silver["trans"].copy()}
    changed["trans"].loc[changed["trans"]["trans_id"] == "5", ["amount", "balance"]] = [90000.0, 90500.0]
    after = monthly(changed)
    past = base.index[base.index.get_level_values("reference_month") < D("1993-03-31")]
    pd.testing.assert_frame_equal(base.loc[past], after.loc[past])


# --- checks ---


def test_check_gold_passes_on_valid_tables(silver: dict[str, pd.DataFrame]):
    gold = build_gold(silver)
    check_gold(gold["gold_account"], gold["gold_account_monthly_movements"], silver["account"])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda a, m: (pd.concat([a, a.iloc[:1]]), m), "account_id: chave duplicada"),
        (lambda a, m: (a, pd.concat([m, m.iloc[:1]])), "duplicado"),
        (lambda a, m: (a.iloc[:1], m), "diferentes das da Silver"),
        (lambda a, m: (a.assign(owner_gender=pd.NA), m), "nulos em"),
        (lambda a, m: (a, m.assign(closing_balance=pd.NA)), "nulos em"),
        (lambda a, m: (a, m.drop(m.index[1])), "não contíguos"),
        (lambda a, m: (a, m.assign(outflow_3m_sum=-1.0)), "outflow_3m_sum"),
        (lambda a, m: (a, m.assign(previous_month_outflow=999.0)), "previous_month_outflow"),
        (lambda a, m: (a, m.assign(reference_month=m["reference_month"] - pd.offsets.Day(1))), "fim de mês"),
    ],
)
def test_check_gold_detects_violations(silver: dict[str, pd.DataFrame], mutate, message: str):  # type: ignore[no-untyped-def]
    gold = build_gold(silver)
    account, mth = mutate(gold["gold_account"], gold["gold_account_monthly_movements"])
    with pytest.raises(GoldQualityError, match=message):
        check_gold(account, mth, silver["account"])


# --- I/O ---


def _write_silver(silver: dict[str, pd.DataFrame], silver_dir: Path) -> None:
    for name in SILVER_TABLES:
        write_parquet_atomic(silver[name], silver_dir / f"{name}.parquet")


def test_silver_to_gold_is_idempotent_and_leaves_no_tmp(silver: dict[str, pd.DataFrame], tmp_path: Path):
    _write_silver(silver, tmp_path / "silver")
    first = silver_to_gold(tmp_path / "silver", tmp_path / "gold")
    assert first == silver_to_gold(tmp_path / "silver", tmp_path / "gold")
    assert sorted(p.name for p in (tmp_path / "gold").iterdir()) == sorted(f"{t}.parquet" for t in GOLD_TABLES)
    assert len(pd.read_parquet(tmp_path / "gold" / "gold_account.parquet")) == 2


def test_silver_to_gold_writes_nothing_if_validation_fails(silver: dict[str, pd.DataFrame], tmp_path: Path):
    silver["client"] = silver["client"].assign(gender=pd.NA)
    _write_silver(silver, tmp_path / "silver")
    with pytest.raises(GoldQualityError):
        silver_to_gold(tmp_path / "silver", tmp_path / "gold")
    assert not (tmp_path / "gold").exists()


def test_silver_to_gold_fails_if_silver_is_incomplete(tmp_path: Path):
    (tmp_path / "silver").mkdir()
    with pytest.raises(FileNotFoundError, match="Faltam"):
        silver_to_gold(tmp_path / "silver", tmp_path / "gold")
