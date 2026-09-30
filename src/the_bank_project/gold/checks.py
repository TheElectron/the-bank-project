"""
    Validações de qualidade para a Gold.
"""

import numpy as np
import pandas as pd

NOT_NULL_ACCOUNT = ["account_id", "account_open_date", "account_frequency", "district_id", "owner_client_id",
                    "owner_gender", "owner_birth_date", "has_card", "has_loan", "dependent_count"]  # fmt: skip
NOT_NULL_MONTHLY = ["account_id", "reference_month", "account_age_months", "transaction_count", "inflow_amount",
                    "outflow_amount", "net_flow", "opening_balance", "closing_balance", "avg_balance",
                    "outflow_3m_avg", "outflow_3m_sum", "outflow_6m_avg", "inflow_3m_avg", "avg_balance_3m",
                    "transaction_count_3m_avg"]  # fmt: skip
TOLERANCE = 0.01


class GoldQualityError(ValueError):
    """Uma regra de qualidade foi violada."""


def _null_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [c for c in columns if df[c].isna().any()]


def check_gold(account: pd.DataFrame, monthly: pd.DataFrame, silver_account: pd.DataFrame) -> None:
    """
        Valida as tabelas da camada Gold e gera `GoldQualityError` caso encontre violações das regras de qualidade.
        Regras: 
        - PKs únicas; 
        - Valores não nulos nas colunas obrigatórias; 
        - Todas as contas da Silver estão na Gold; 
        - Todas as contas estão presentes em ambas as tabelas; 
        - Não existem lacunas nos meses na tabela de movimentações mensais; 
        - Valores coerentes (`outflow_3m_sum` >= saída do mês, lag de um mês bate com o mês anterior, etc.);
    """
    errors: list[str] = []
    if account["account_id"].duplicated().any():
        errors.append("gold_account.account_id: chave duplicada")
    if monthly.duplicated(["account_id", "reference_month"]).any():
        errors.append("gold_account_monthly_movements: (account_id, reference_month) duplicado")
    if set(account["account_id"]) != set(silver_account["account_id"]):
        errors.append("gold_account: discrepância entre o total de contas da Silver e Gold")
    if not set(monthly["account_id"]) <= set(account["account_id"]):
        errors.append("gold_account_monthly_movements: conta sem correspondente em gold_account")
    if nulls := _null_columns(account, NOT_NULL_ACCOUNT):
        errors.append(f"gold_account: nulos em {nulls}")
    if nulls := _null_columns(monthly, NOT_NULL_MONTHLY):
        errors.append(f"gold_account_monthly_movements: nulos em {nulls}")

    m = monthly.sort_values(["account_id", "reference_month"])
    g = m.groupby("account_id")
    step = (m["reference_month"].dt.year * 12 + m["reference_month"].dt.month).groupby(m["account_id"]).diff()
    if (step.dropna() != 1).any():
        errors.append("gold_account_monthly_movements: meses não contíguos numa conta")
    if (m["outflow_3m_sum"] < m["outflow_amount"] - TOLERANCE).any():
        errors.append("gold_account_monthly_movements: outflow_3m_sum menor que a saída do mês")
    lag = g["outflow_amount"].shift()
    if not np.allclose(m["previous_month_outflow"].fillna(0), lag.fillna(0)):
        errors.append("gold_account_monthly_movements: previous_month_outflow não bate com o mês anterior")
    if (m["reference_month"] != m["reference_month"] + pd.offsets.MonthEnd(0)).any():
        errors.append("gold_account_monthly_movements: reference_month não é fim de mês")
    if errors:
        raise GoldQualityError("Gold inválida:\n- " + "\n- ".join(errors))
