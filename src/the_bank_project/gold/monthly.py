"""`gold_account_monthly_movements`: série mensal por conta a partir de `trans`."""

import numpy as np
import pandas as pd

KEYS = ["account_id", "reference_month"]

# Coluna da Gold -> (coluna da Silver, valores). Soma do valor / contagem das linhas que casam.
AMOUNT_RULES = {
    "cash_withdrawal": ("operation", "SAQUE_DINHEIRO"),
    "card_withdrawal": ("operation", "SAQUE_CARTAO"),
    "transfer_out": ("operation", "TRANSFERENCIA_ENVIADA"),
    "transfer_in": ("operation", "TRANSFERENCIA_RECEBIDA"),
    "loan_payment": ("k_symbol", "PAGAMENTO_EMPRESTIMO"),
    "insurance_payment": ("k_symbol", "SEGURO"),
    "domestic_payment": ("k_symbol", "PAGAMENTO_DOMESTICO"),
    "interest": ("k_symbol", "JUROS"),
    "penalty_interest": ("k_symbol", "JUROS_PENALIDADE"),
}
# `leasing_payment_amount` do desenho original ficou de fora: `LEASING` só existe em `order`, nunca em `trans`.
COUNT_RULES = ("loan_payment", "transfer_out", "transfer_in", "cash_withdrawal", "card_withdrawal")
ZERO_FILL = [
    "transaction_count", "active_days", "credit_transaction_count", "debit_transaction_count",
    "withdrawal_transaction_count", "transfer_transaction_count", "inflow_amount", "outflow_amount", "net_flow",
    *(f"{name}_amount" for name in AMOUNT_RULES), *(f"{name}_count" for name in COUNT_RULES),
]  # fmt: skip
COUNT_COLUMNS = [c for c in ZERO_FILL if c.endswith("_count") or c == "active_days"]


def _month_end(dates: pd.Series) -> pd.Series:
    return dates + pd.offsets.MonthEnd(0)


def _day_balances(trans: pd.DataFrame) -> pd.DataFrame:
    """Saldo de abertura e de fechamento de cada dia com movimento, por conta.

    Dentro do mesmo dia o `trans_id` não segue a ordem real, então a última
    transação do dia é a única cuja `balance` não é o saldo anterior
    (`balance - valor com sinal`) de outra do mesmo dia — e a primeira é a
    inversa. Se a heurística não fechar (valores repetidos), usa a de maior
    `trans_id`.
    """
    sign = np.where(trans["type"] == "CREDITO", 1.0, -1.0)
    t = pd.DataFrame({
        "account_id": trans["account_id"], "date": trans["date"], "tid": trans["trans_id"].astype("int64"),
        "close": (trans["balance"] * 100).round().astype("int64"),
        "open": ((trans["balance"] - sign * trans["amount"]) * 100).round().astype("int64"),
    }).sort_values(["account_id", "date", "tid"])  # fmt: skip
    keys = ["account_id", "date"]
    closes = pd.MultiIndex.from_frame(t[[*keys, "close"]])
    opens = pd.MultiIndex.from_frame(t[[*keys, "open"]])
    last = t[~closes.isin(opens.set_names([*keys, "close"]))]
    first = t[~opens.isin(closes.set_names([*keys, "open"]))]
    days = t.groupby(keys).agg(close=("close", "last"), open=("open", "first"))  # fallback por trans_id
    days.update(last.groupby(keys)[["close"]].first())
    days.update(first.groupby(keys)[["open"]].first())
    return (days / 100).reset_index()


def _aggregate(trans: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (conta, mês) com movimento."""
    t = trans.assign(reference_month=_month_end(trans["date"]))
    credit = t["type"] == "CREDITO"
    amount = t["amount"].astype("float64")
    cols: dict[str, pd.Series] = {
        "credit_transaction_count": credit,
        "debit_transaction_count": ~credit,
        "withdrawal_transaction_count": t["operation"].isin(["SAQUE_DINHEIRO", "SAQUE_CARTAO"]),
        "transfer_transaction_count": t["operation"].isin(["TRANSFERENCIA_ENVIADA", "TRANSFERENCIA_RECEBIDA"]),
        "inflow_amount": amount.where(credit, 0.0),
        "outflow_amount": amount.where(~credit, 0.0),
    }
    for name, (column, value) in AMOUNT_RULES.items():
        match = t[column] == value
        cols[f"{name}_amount"] = amount.where(match, 0.0)
        if name in COUNT_RULES:
            cols[f"{name}_count"] = match
    work = pd.DataFrame({**cols, "account_id": t["account_id"], "reference_month": t["reference_month"],
                         "date": t["date"], "amount": amount, "balance": t["balance"].astype("float64"),
                         "trans_id": t["trans_id"]})  # fmt: skip
    g = work.groupby(KEYS)
    agg = g.agg(
        transaction_count=("trans_id", "size"), active_days=("date", "nunique"),
        avg_transaction_amount=("amount", "mean"), min_transaction_amount=("amount", "min"),
        max_transaction_amount=("amount", "max"), avg_balance=("balance", "mean"),
        min_balance=("balance", "min"), max_balance=("balance", "max"),
        **{c: (c, "sum") for c in cols},
    )  # fmt: skip
    agg["net_flow"] = agg["inflow_amount"] - agg["outflow_amount"]
    days = _day_balances(trans)
    days["reference_month"] = _month_end(days["date"])
    days = days.sort_values("date")
    dg = days.groupby(KEYS)
    agg["opening_balance"] = dg["open"].first()
    agg["closing_balance"] = dg["close"].last()
    return agg.reset_index()


def _fill_gaps(agg: pd.DataFrame) -> pd.DataFrame:
    """Um registro por mês entre o primeiro e o último mês com movimento de cada conta.

    Meses sem transação entram com fluxos/contagens 0 e saldo carregado do mês
    anterior, senão janelas e `LAG` olhariam para meses distantes.
    """
    ym = agg["reference_month"].dt.year * 12 + agg["reference_month"].dt.month - 1
    span = ym.groupby(agg["account_id"]).agg(["min", "max"])
    n = (span["max"] - span["min"] + 1).to_numpy()
    account = np.repeat(span.index.to_numpy(), n)
    offset = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    months = np.repeat(span["min"].to_numpy(), n) + offset
    full = pd.DataFrame({"account_id": account, "reference_month": pd.to_datetime(
        {"year": months // 12, "month": months % 12 + 1, "day": 1}) + pd.offsets.MonthEnd(0)})  # fmt: skip
    df = full.merge(agg, on=KEYS, how="left", validate="1:1").sort_values(KEYS, ignore_index=True)
    df[ZERO_FILL] = df[ZERO_FILL].fillna(0)
    df[COUNT_COLUMNS] = df[COUNT_COLUMNS].astype("int64")
    df["closing_balance"] = df.groupby("account_id")["closing_balance"].ffill()
    df["opening_balance"] = df["opening_balance"].fillna(df["closing_balance"])
    for col in ("avg_balance", "min_balance", "max_balance"):
        df[col] = df[col].fillna(df["closing_balance"])
    return df


def _window_features(df: pd.DataFrame) -> pd.DataFrame:
    """Lags, médias/somas móveis e variações. Só olham para trás e incluem o mês de referência."""
    g = df.groupby("account_id")

    def rolling(col: str, window: int, how: str) -> pd.Series:
        r = g[col].rolling(window, min_periods=1)
        return getattr(r, how)().reset_index(level=0, drop=True)

    df["previous_month_outflow"] = g["outflow_amount"].shift()
    df["previous_month_inflow"] = g["inflow_amount"].shift()
    df["outflow_3m_avg"] = rolling("outflow_amount", 3, "mean")
    df["outflow_3m_sum"] = rolling("outflow_amount", 3, "sum")
    df["outflow_6m_avg"] = rolling("outflow_amount", 6, "mean")
    df["inflow_3m_avg"] = rolling("inflow_amount", 3, "mean")
    df["avg_balance_3m"] = rolling("avg_balance", 3, "mean")
    df["transaction_count_3m_avg"] = rolling("transaction_count", 3, "mean")
    for flow in ("outflow", "inflow"):
        prev = df[f"previous_month_{flow}"].replace(0, np.nan)  # base 0: variação indefinida, não infinita
        df[f"{flow}_mom_change"] = (df[f"{flow}_amount"] - prev) / prev
    df["balance_mom_change"] = df["closing_balance"] - g["closing_balance"].shift()
    return df


def build_gold_account_monthly(trans: pd.DataFrame, account: pd.DataFrame) -> pd.DataFrame:
    """Silver → `gold_account_monthly_movements` (grão `account_id` x `reference_month`).

    `reference_month` é o **último dia** do mês: é quando as features do mês
    ficam completas, então serve de `event_timestamp` no Feast sem vazar
    informação do mês para consultas feitas antes dele terminar.
    """
    df = _window_features(_fill_gaps(_aggregate(trans)))
    opened = df["account_id"].map(account.set_index("account_id")["date"])
    df["year"] = df["reference_month"].dt.year
    df["month"] = df["reference_month"].dt.month
    df["account_age_months"] = (df["year"] - opened.dt.year) * 12 + df["month"] - opened.dt.month
    df[["year", "month", "account_age_months"]] = df[["year", "month", "account_age_months"]].astype("int64")
    first = ["account_id", "reference_month", "account_age_months", "year", "month"]
    return df[[*first, *(c for c in df.columns if c not in first)]]
