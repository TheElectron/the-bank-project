"""Bronze → Silver: funções puras por tabela + `bronze_to_silver` (I/O)."""

import logging
from pathlib import Path

import pandas as pd

from the_bank_project.io import write_parquet_atomic
from the_bank_project.silver.checks import check_silver

logger = logging.getLogger(__name__)

BRONZE_TABLES = ("account", "card", "client", "disp", "district", "loan", "order", "trans")
SILVER_TABLES = ("district", "client", "account", "order", "trans")

# Códigos tchecos do Berka → rótulos em português (ver README, "Camada Silver").
FREQUENCY = {"POPLATEK MESICNE": "MENSAL", "POPLATEK TYDNE": "SEMANAL", "POPLATEK PO OBRATU": "POR_TRANSACAO"}
RELATIONSHIP = {"OWNER": "TITULAR", "DISPONENT": "DEPENDENTE"}
TRANS_TYPE = {"PRIJEM": "CREDITO", "VYDAJ": "DEBITO", "VYBER": "SAQUE"}
OPERATION = {
    "VYBER KARTOU": "SAQUE_CARTAO",
    "VKLAD": "DEPOSITO_DINHEIRO",
    "PREVOD Z UCTU": "TRANSFERENCIA_RECEBIDA",
    "VYBER": "SAQUE_DINHEIRO",
    "PREVOD NA UCET": "TRANSFERENCIA_ENVIADA",
}
K_SYMBOL = {
    "POJISTNE": "SEGURO",
    "SLUZBY": "TARIFA_EXTRATO",
    "UROK": "JUROS",
    "SANKC. UROK": "JUROS_PENALIDADE",
    "SIPO": "PAGAMENTO_DOMESTICO",
    "DUCHOD": "PENSAO",
    "UVER": "PAGAMENTO_EMPRESTIMO",
    "LEASING": "LEASING",
}

DISTRICT_COLUMNS = {
    "A1": "district_id", "A2": "district_name", "A3": "region", "A4": "population",
    "A5": "municipalities_under_499", "A6": "municipalities_500_1999", "A7": "municipalities_2000_9999",
    "A8": "municipalities_over_10000", "A9": "cities", "A10": "urban_population_ratio", "A11": "average_salary",
    "A12": "unemployment_rate_1995", "A13": "unemployment_rate_1996", "A14": "entrepreneurs_per_1000",
    "A15": "crimes_1995", "A16": "crimes_1996",
}  # fmt: skip
DISTRICT_INT = ("population", "municipalities_under_499", "municipalities_500_1999", "municipalities_2000_9999",
                "municipalities_over_10000", "cities", "average_salary", "entrepreneurs_per_1000",
                "crimes_1995", "crimes_1996")  # fmt: skip
DISTRICT_FLOAT = ("urban_population_ratio", "unemployment_rate_1995", "unemployment_rate_1996")


def _blank_to_na(s: pd.Series) -> pd.Series:
    """Troca os placeholders de nulo do Berka (`""`, `" "`, `"?"`) por NA."""
    s = s.astype("string").str.strip()
    return s.mask(s.isin(["", "?"]))


def _translate(s: pd.Series, mapping: dict[str, str]) -> pd.Series:
    """Traduz uma categórica; um código fora do mapa é erro (o schema mudou), não vira nulo."""
    s = _blank_to_na(s)
    out = s.map(mapping).astype("string")
    unknown = sorted(set(s[out.isna() & s.notna()]))
    if unknown:
        raise ValueError(f"Valores fora do mapa de tradução em '{s.name}': {unknown}")
    return out


def _to_date(s: pd.Series) -> pd.Series:
    """`AAMMDD` (com ou sem hora) → datetime. O dataset cobre só o século XX."""
    return pd.to_datetime("19" + s.astype("string").str[:6], format="%Y%m%d")


def _num(s: pd.Series, dtype: str) -> pd.Series:
    return pd.to_numeric(_blank_to_na(s)).astype(dtype)


def build_district(district: pd.DataFrame) -> pd.DataFrame:
    """Renomeia A1..A16 e tipa; `?` (2 campos do distrito 69) vira nulo."""
    df = district.rename(columns=DISTRICT_COLUMNS)
    for col in DISTRICT_INT:
        df[col] = _num(df[col], "Int64")
    for col in DISTRICT_FLOAT:
        df[col] = _num(df[col], "Float64")
    return df


def build_client(client: pd.DataFrame, disp: pd.DataFrame, card: pd.DataFrame) -> pd.DataFrame:
    """Consolida client + disp + card. Os merges são 1:1 e `validate=` falha se deixarem de ser."""
    df = client.merge(disp.rename(columns={"type": "relationship_type"}), on="client_id", how="inner", validate="1:1")
    if len(df) != len(client):
        raise ValueError("Há clientes sem `disp` (ou `disp` de cliente inexistente).")
    card = card.rename(columns={"type": "card_type", "issued": "card_issued"})
    df = df.merge(card, on="disp_id", how="left", validate="1:1")
    month = df["birth_number"].str[2:4].astype(int)
    female = month > 50
    df["gender"] = female.map({True: "F", False: "M"}).astype("string")
    birth = (
        "19" + df["birth_number"].str[:2] + (month - 50 * female).astype(str).str.zfill(2) + df["birth_number"].str[4:6]
    )
    df["birth_date"] = pd.to_datetime(birth, format="%Y%m%d")
    df["relationship_type"] = _translate(df["relationship_type"], RELATIONSHIP)
    df["card_issued"] = _to_date(df["card_issued"]).where(df["card_id"].notna())
    cols = ["client_id", "account_id", "relationship_type", "district_id", "gender", "birth_date",
            "card_id", "card_type", "card_issued"]  # fmt: skip
    return df[cols]


def build_account(account: pd.DataFrame, loan: pd.DataFrame) -> pd.DataFrame:
    """Consolida account + loan (no máximo 1 empréstimo por conta)."""
    loan = loan.rename(columns={c: f"loan_{c}" for c in ("date", "amount", "duration", "payments", "status")})
    df = account.merge(loan, on="account_id", how="left", validate="1:1")
    df["frequency"] = _translate(df["frequency"], FREQUENCY)
    df["date"] = _to_date(df["date"])
    df["loan_date"] = _to_date(df["loan_date"])
    df["loan_amount"] = _num(df["loan_amount"], "Float64")
    df["loan_duration"] = _num(df["loan_duration"], "Int64")
    df["loan_payments"] = _num(df["loan_payments"], "Float64")
    return df[["account_id", "district_id", "frequency", "date", "loan_id", "loan_date", "loan_amount",
               "loan_duration", "loan_payments", "loan_status"]]  # fmt: skip


def build_order(order: pd.DataFrame) -> pd.DataFrame:
    """Tipa `amount` e traduz `k_symbol` (branco vira nulo)."""
    df = order.copy()
    df["amount"] = _num(df["amount"], "Float64")
    df["k_symbol"] = _translate(df["k_symbol"], K_SYMBOL)
    return df


def build_trans(trans: pd.DataFrame) -> pd.DataFrame:
    """Tipa e traduz `trans`; branco em `operation`/`k_symbol`/`bank`/`account` vira nulo."""
    df = trans.copy()
    df["date"] = _to_date(df["date"])
    df["amount"] = _num(df["amount"], "Float64")
    df["balance"] = _num(df["balance"], "Float64")
    df["type"] = _translate(df["type"], TRANS_TYPE)
    df["operation"] = _translate(df["operation"], OPERATION)
    df["k_symbol"] = _translate(df["k_symbol"], K_SYMBOL)
    df["bank"] = _blank_to_na(df["bank"])
    df["account"] = _blank_to_na(df["account"])
    return df


def build_silver(bronze: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Função pura: tabelas da Bronze (tudo texto) → 5 tabelas da Silver, já validadas por `check_silver`."""
    silver = {
        "district": build_district(bronze["district"]),
        "client": build_client(bronze["client"], bronze["disp"], bronze["card"]),
        "account": build_account(bronze["account"], bronze["loan"]),
        "order": build_order(bronze["order"]),
        "trans": build_trans(bronze["trans"]),
    }
    check_silver(silver)
    return silver


def bronze_to_silver(bronze_dir: Path, silver_dir: Path) -> list[Path]:
    """Lê a Bronze, constrói e valida a Silver e grava um parquet por tabela (idempotente).

    Nada é gravado se a validação falhar.

    Raises:
        FileNotFoundError: se faltar algum parquet da Bronze.
    """
    missing = [t for t in BRONZE_TABLES if not (bronze_dir / f"{t}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"Faltam em {bronze_dir}: {missing}. Rode a ingestão antes.")
    silver = build_silver({t: pd.read_parquet(bronze_dir / f"{t}.parquet") for t in BRONZE_TABLES})
    paths = []
    for name in SILVER_TABLES:
        paths.append(write_parquet_atomic(silver[name], silver_dir / f"{name}.parquet"))
        logger.info("%s -> %s (%d linhas, %d colunas)", name, paths[-1].name, *silver[name].shape)
    return paths
