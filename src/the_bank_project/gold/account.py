"""`gold_account`: um registro por conta, com os atributos do titular, do distrito e do empréstimo."""

import pandas as pd

DISTRICT_COLUMNS = {
    "district_name": "district_name",
    "region": "district_region",
    "population": "district_population",
    "urban_population_ratio": "district_urban_ratio",
    "average_salary": "district_average_salary",
    "unemployment_rate_1995": "district_unemployment_1995",
    "unemployment_rate_1996": "district_unemployment_1996",
    "entrepreneurs_per_1000": "district_entrepreneurs_per_1000",
    "crimes_1995": "district_crimes_1995",
    "crimes_1996": "district_crimes_1996",
}


def build_gold_account(account: pd.DataFrame, client: pd.DataFrame, district: pd.DataFrame) -> pd.DataFrame:
    """Silver → `gold_account` (grão `account_id`).

    O distrito das features é o da conta; o de residência do titular segue em
    `owner_district_id`. Cartão só existe para titular (garantido pela Silver),
    então `card_*` já descreve o cartão da conta.
    """
    owner = client.loc[client["relationship_type"] == "TITULAR"]
    owner = owner.rename(columns={"client_id": "owner_client_id", "gender": "owner_gender",
                                  "birth_date": "owner_birth_date", "district_id": "owner_district_id"})  # fmt: skip
    dependents = client.loc[client["relationship_type"] == "DEPENDENTE"].groupby("account_id").size()
    dist = district.rename(columns=DISTRICT_COLUMNS)[["district_id", *DISTRICT_COLUMNS.values()]]

    df = account.rename(columns={"date": "account_open_date", "frequency": "account_frequency"})
    df = df.merge(owner.drop(columns="relationship_type"), on="account_id", how="left", validate="1:1")
    df = df.merge(dist, on="district_id", how="left", validate="m:1")
    df["dependent_count"] = df["account_id"].map(dependents).fillna(0).astype("int64")
    df["has_card"] = df["card_id"].notna()
    df["has_loan"] = df["loan_id"].notna()
    df["loan_payment_ratio"] = (df["loan_payments"] / df["loan_amount"]).astype("float64")
    for col in ("loan_amount", "loan_payments"):
        df[col] = df[col].astype("float64")
    df = df.rename(columns={"card_issued": "card_issued_date"})
    return df[[
        "account_id", "account_open_date", "account_frequency", "district_id", *DISTRICT_COLUMNS.values(),
        "owner_client_id", "owner_gender", "owner_birth_date", "owner_district_id", "dependent_count",
        "has_card", "card_type", "card_issued_date",
        "has_loan", "loan_date", "loan_amount", "loan_duration", "loan_payments", "loan_payment_ratio", "loan_status",
    ]]  # fmt: skip
