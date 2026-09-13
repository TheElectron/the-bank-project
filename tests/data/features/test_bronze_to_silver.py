"""Testes de `bronze_to_silver.py`: os merges 1:1 da reorganização Silver (ver README, "Reorganização na Silver").

`pd.merge(..., validate="one_to_one")` já barra a gravação em runtime se a
premissa de cardinalidade deixar de valer nos dados reais — estes testes
fixam esse comportamento contra regressão, sem depender do dataset Berka.
"""

import pandas as pd
import pytest

from src.data.features.bronze_to_silver import build_account_table, build_client_table


def _client_df() -> pd.DataFrame:
    return pd.DataFrame({
        "client_id": ["C1", "C2"],
        "district_id": ["D1", "D1"],
        "gender": ["M", "F"],
        "birth_date": pd.to_datetime(["1970-01-01", "1980-02-02"]),
    })


def _disp_df() -> pd.DataFrame:
    return pd.DataFrame({
        "disp_id": ["P1", "P2"],
        "client_id": ["C1", "C2"],
        "account_id": ["A1", "A2"],
        "type": ["TITULAR", "TITULAR"],
    })


def _card_df() -> pd.DataFrame:
    return pd.DataFrame({
        "disp_id": ["P1"],
        "card_id": ["K1"],
        "type": ["classic"],
        "issued": pd.to_datetime(["1995-01-01"]),
    })


def test_build_client_table_merges_disp_and_card_one_to_one():
    result = build_client_table(_client_df(), _disp_df(), _card_df())

    assert len(result) == 2  # nenhuma linha duplicada pelos 2 merges
    c1 = result.set_index("client_id").loc["C1"]
    assert c1["account_id"] == "A1"
    assert c1["card_id"] == "K1"
    c2 = result.set_index("client_id").loc["C2"]
    assert pd.isna(c2["card_id"])  # sem cartão -> nulo (how="left"), não descartado


def test_build_client_table_raises_when_client_has_more_than_one_disp():
    """Um `client_id` em 2 disps violaria a premissa 'todo client tem exatamente 1 disp' do README."""
    disp_duplicado = pd.concat([_disp_df(), pd.DataFrame({
        "disp_id": ["P3"], "client_id": ["C1"], "account_id": ["A3"], "type": ["DEPENDENTE"],
    })], ignore_index=True)

    with pytest.raises(pd.errors.MergeError):
        build_client_table(_client_df(), disp_duplicado, _card_df())


def test_build_client_table_raises_when_disp_has_more_than_one_card():
    """Um `disp_id` com 2 cards violaria a premissa 'nenhum titular tem mais de 1 cartão' do README."""
    card_duplicado = pd.concat([_card_df(), pd.DataFrame({
        "disp_id": ["P1"], "card_id": ["K2"], "type": ["gold"], "issued": pd.to_datetime(["1996-01-01"]),
    })], ignore_index=True)

    with pytest.raises(pd.errors.MergeError):
        build_client_table(_client_df(), _disp_df(), card_duplicado)


def _account_df() -> pd.DataFrame:
    return pd.DataFrame({
        "account_id": ["A1", "A2"],
        "district_id": ["D1", "D1"],
        "frequency": ["MENSAL", "MENSAL"],
        "date": pd.to_datetime(["1993-01-01", "1994-01-01"]),
    })


def _loan_df() -> pd.DataFrame:
    return pd.DataFrame({
        "loan_id": ["L1"],
        "account_id": ["A1"],
        "date": pd.to_datetime(["1996-01-01"]),
        "amount": [10_000.0],
        "duration": [24],
        "payments": [500.0],
        "status": ["ATIVO ADIMPLENTE"],
    })


def test_build_account_table_merges_loan_one_to_one():
    result = build_account_table(_account_df(), _loan_df())

    assert len(result) == 2
    a1 = result.set_index("account_id").loc["A1"]
    assert a1["loan_id"] == "L1"
    a2 = result.set_index("account_id").loc["A2"]
    assert pd.isna(a2["loan_id"])  # sem empréstimo -> nulo, não descartado


def test_build_account_table_raises_when_account_has_more_than_one_loan():
    """Um `account_id` em 2 loans violaria a premissa 'toda account tem no máximo 1 loan' do README."""
    loan_duplicado = pd.concat([_loan_df(), pd.DataFrame({
        "loan_id": ["L2"], "account_id": ["A1"], "date": pd.to_datetime(["1997-01-01"]),
        "amount": [5_000.0], "duration": [12], "payments": [450.0], "status": ["ATIVO ADIMPLENTE"],
    })], ignore_index=True)

    with pytest.raises(pd.errors.MergeError):
        build_account_table(_account_df(), loan_duplicado)
