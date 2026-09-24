from pathlib import Path

import pandas as pd
import pytest

from the_bank_project.io import write_parquet_atomic
from the_bank_project.silver import DataQualityError, bronze_to_silver, build_silver
from the_bank_project.silver.transform import BRONZE_TABLES, SILVER_TABLES


def _df(rows: list[dict[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype="string")


@pytest.fixture
def bronze() -> dict[str, pd.DataFrame]:
    """Bronze sintética mínima: 2 contas, 3 clientes (1 dependente), 1 cartão, 1 empréstimo."""
    district = {f"A{i}": "1" for i in range(1, 17)} | {
        "A2": "Praha",
        "A3": "Prague",
        "A10": "46.7",
        "A12": "?",
        "A15": "?",
    }
    return {
        "district": _df([district, district | {"A1": "2"}]),
        "account": _df([
            {"account_id": "1", "district_id": "1", "frequency": "POPLATEK MESICNE", "date": "930101"},
            {"account_id": "2", "district_id": "2", "frequency": "POPLATEK TYDNE", "date": "950315"},
        ]),
        "client": _df([
            {"client_id": "1", "birth_number": "706213", "district_id": "1"},  # mulher, 1970-12-13
            {"client_id": "2", "birth_number": "450204", "district_id": "2"},  # homem, 1945-02-04
            {"client_id": "3", "birth_number": "801231", "district_id": "2"},  # homem (dependente)
        ]),
        "disp": _df([
            {"disp_id": "1", "client_id": "1", "account_id": "1", "type": "OWNER"},
            {"disp_id": "2", "client_id": "2", "account_id": "2", "type": "OWNER"},
            {"disp_id": "3", "client_id": "3", "account_id": "2", "type": "DISPONENT"},
        ]),
        "card": _df([{"card_id": "9", "disp_id": "2", "type": "gold", "issued": "931107 00:00:00"}]),
        "loan": _df([{"loan_id": "7", "account_id": "1", "date": "930705", "amount": "96396", "duration": "12",
                      "payments": "8033.00", "status": "A"}]),
        "order": _df([
            {"order_id": "1", "account_id": "1", "bank_to": "YZ", "account_to": "8",
             "amount": "2452.00", "k_symbol": "SIPO"},
            {"order_id": "2", "account_id": "2", "bank_to": "AB", "account_to": "9",
             "amount": "10.50", "k_symbol": " "},
        ]),
        "trans": _df([
            {"trans_id": "1", "account_id": "1", "date": "930101", "type": "PRIJEM", "operation": "VKLAD",
             "amount": "700.00",
             "balance": "700.00", "k_symbol": "", "bank": "", "account": ""},
            {"trans_id": "2", "account_id": "1", "date": "930102", "type": "VYDAJ", "operation": "PREVOD NA UCET",
             "amount": "50.00", "balance": "650.00", "k_symbol": "SIPO", "bank": "AB", "account": "123"},
        ]),
    }  # fmt: skip


def test_build_silver_returns_the_5_tables_with_consolidated_columns(bronze: dict[str, pd.DataFrame]):
    silver = build_silver(bronze)
    assert set(silver) == set(SILVER_TABLES)
    assert len(silver["client"]) == 3 and len(silver["account"]) == 2
    assert {"card_id", "card_type", "card_issued", "relationship_type"} <= set(silver["client"].columns)
    assert {"loan_id", "loan_amount", "loan_status"} <= set(silver["account"].columns)


def test_district_renames_types_and_nulls_question_marks(bronze: dict[str, pd.DataFrame]):
    d = build_silver(bronze)["district"]
    assert {"district_id", "average_salary", "crimes_1996"} <= set(d.columns)
    assert d["urban_population_ratio"].iloc[0] == 46.7
    assert d["unemployment_rate_1995"].isna().all() and d["crimes_1995"].isna().all()  # "?"
    assert str(d["population"].dtype) == "Int64"


def test_client_gender_and_birth_date_from_birth_number(bronze: dict[str, pd.DataFrame]):
    c = build_silver(bronze)["client"].set_index("client_id")
    assert (c.loc["1", "gender"], c.loc["1", "birth_date"]) == ("F", pd.Timestamp("1970-12-13"))
    assert (c.loc["2", "gender"], c.loc["2", "birth_date"]) == ("M", pd.Timestamp("1945-02-04"))


def test_client_translates_role_and_only_owner_has_card(bronze: dict[str, pd.DataFrame]):
    c = build_silver(bronze)["client"].set_index("client_id")
    assert c["relationship_type"].to_dict() == {"1": "TITULAR", "2": "TITULAR", "3": "DEPENDENTE"}
    assert c.loc["2", "card_id"] == "9" and c.loc["2", "card_issued"] == pd.Timestamp("1993-11-07")
    assert c[["card_id", "card_issued"]].drop("2").isna().all().all()


def test_account_left_joins_loan_and_types_columns(bronze: dict[str, pd.DataFrame]):
    a = build_silver(bronze)["account"].set_index("account_id")
    assert a.loc["1", "loan_amount"] == 96396 and a.loc["1", "loan_duration"] == 12
    assert a.loc["1", "date"] == pd.Timestamp("1993-01-01") and a.loc["1", "frequency"] == "MENSAL"
    assert a.loc["2", ["loan_id", "loan_date", "loan_amount"]].isna().all()


def test_trans_and_order_placeholders_become_null_and_codes_are_translated(bronze: dict[str, pd.DataFrame]):
    silver = build_silver(bronze)
    t = silver["trans"]
    assert t["type"].tolist() == ["CREDITO", "DEBITO"]
    assert t["operation"].tolist() == ["DEPOSITO_DINHEIRO", "TRANSFERENCIA_ENVIADA"]
    assert pd.isna(t["k_symbol"].iloc[0]) and t["k_symbol"].iloc[1] == "PAGAMENTO_DOMESTICO"
    assert t[["bank", "account"]].iloc[0].isna().all() and t["bank"].iloc[1] == "AB"
    assert t["amount"].tolist() == [700.0, 50.0]
    o = silver["order"]
    assert o["k_symbol"].iloc[0] == "PAGAMENTO_DOMESTICO" and pd.isna(o["k_symbol"].iloc[1])


def test_unknown_category_code_fails_instead_of_becoming_null(bronze: dict[str, pd.DataFrame]):
    bronze["trans"].loc[0, "type"] = "NOVO"
    with pytest.raises(ValueError, match="fora do mapa"):
        build_silver(bronze)


# --- as validações 1:1 dos merges (antes manuais no README) ---


def test_merge_fails_if_client_has_two_disps(bronze: dict[str, pd.DataFrame]):
    bronze["disp"] = pd.concat(
        [bronze["disp"], _df([{"disp_id": "4", "client_id": "3", "account_id": "1", "type": "DISPONENT"}])]
    )
    with pytest.raises(pd.errors.MergeError):
        build_silver(bronze)


def test_merge_fails_if_disp_has_two_cards(bronze: dict[str, pd.DataFrame]):
    bronze["card"] = pd.concat(
        [bronze["card"], _df([{"card_id": "10", "disp_id": "2", "type": "junior", "issued": "940101"}])]
    )
    with pytest.raises(pd.errors.MergeError):
        build_silver(bronze)


def test_merge_fails_if_account_has_two_loans(bronze: dict[str, pd.DataFrame]):
    extra = bronze["loan"].assign(loan_id="8")
    bronze["loan"] = pd.concat([bronze["loan"], extra])
    with pytest.raises(pd.errors.MergeError):
        build_silver(bronze)


def test_fails_if_client_has_no_disp(bronze: dict[str, pd.DataFrame]):
    bronze["disp"] = bronze["disp"].iloc[:2]
    with pytest.raises(ValueError, match="sem `disp`"):
        build_silver(bronze)


def test_fails_if_dependent_has_card(bronze: dict[str, pd.DataFrame]):
    bronze["card"] = _df([{"card_id": "9", "disp_id": "3", "type": "gold", "issued": "931107"}])
    with pytest.raises(DataQualityError, match="não é TITULAR"):
        build_silver(bronze)


# --- integridade referencial e chaves ---


def test_fails_on_orphan_foreign_key(bronze: dict[str, pd.DataFrame]):
    bronze["trans"].loc[0, "account_id"] = "999"
    with pytest.raises(DataQualityError, match=r"trans\.account_id"):
        build_silver(bronze)


def test_fails_on_duplicate_primary_key(bronze: dict[str, pd.DataFrame]):
    bronze["trans"].loc[1, "trans_id"] = "1"
    with pytest.raises(DataQualityError, match=r"trans\.trans_id"):
        build_silver(bronze)


def test_fails_if_account_has_no_owner(bronze: dict[str, pd.DataFrame]):
    bronze["disp"].loc[1, "type"] = "DISPONENT"
    with pytest.raises(DataQualityError, match="exatamente 1 TITULAR"):
        build_silver(bronze)


# --- I/O ---


def _write_bronze(bronze: dict[str, pd.DataFrame], bronze_dir: Path) -> None:
    for name in BRONZE_TABLES:
        write_parquet_atomic(bronze[name], bronze_dir / f"{name}.parquet")


def test_bronze_to_silver_is_idempotent_and_leaves_no_tmp(bronze: dict[str, pd.DataFrame], tmp_path: Path):
    _write_bronze(bronze, tmp_path / "bronze")
    first = bronze_to_silver(tmp_path / "bronze", tmp_path / "silver")
    second = bronze_to_silver(tmp_path / "bronze", tmp_path / "silver")
    assert first == second and {p.stem for p in first} == set(SILVER_TABLES)
    assert sorted(p.name for p in (tmp_path / "silver").iterdir()) == sorted(f"{t}.parquet" for t in SILVER_TABLES)
    assert len(pd.read_parquet(tmp_path / "silver" / "trans.parquet")) == 2


def test_bronze_to_silver_writes_nothing_if_validation_fails(bronze: dict[str, pd.DataFrame], tmp_path: Path):
    bronze["trans"].loc[0, "account_id"] = "999"
    _write_bronze(bronze, tmp_path / "bronze")
    with pytest.raises(DataQualityError):
        bronze_to_silver(tmp_path / "bronze", tmp_path / "silver")
    assert not (tmp_path / "silver").exists()


def test_bronze_to_silver_fails_if_bronze_is_incomplete(tmp_path: Path):
    (tmp_path / "bronze").mkdir()
    with pytest.raises(FileNotFoundError, match="Faltam"):
        bronze_to_silver(tmp_path / "bronze", tmp_path / "silver")
