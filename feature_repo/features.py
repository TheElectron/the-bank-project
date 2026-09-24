"""Definições do Feast: entidade `account`, as 2 views da Gold e os FeatureServices.

O schema é explícito (contrato): `tests/features/test_contract.py` falha se ele
divergir das colunas da Gold. Não leia a Gold direto em outros módulos; use
`the_bank_project.features`.
"""

from datetime import timedelta

from feast import Entity, FeatureService, FeatureView, Field, FileSource, ValueType
from feast.types import Bool, Float64, Int64, String, UnixTimestamp

account = Entity(
    name="account",
    join_keys=["account_id"],
    value_type=ValueType.STRING,
    description="Conta bancária (entidade do projeto).",
)

account_source = FileSource(
    name="gold_account", path="../data/gold/gold_account.parquet", timestamp_field="account_open_date"
)
monthly_source = FileSource(
    name="gold_account_monthly_movements",
    path="../data/gold/gold_account_monthly_movements.parquet",
    timestamp_field="reference_month",
)

# Cadastral: datada pela abertura da conta e sem expiração. Atenção: card_* e loan_* são
# medidos ao fim do período; mascare-os pela própria data antes de usá-los como feature.
account_static = FeatureView(
    name="account_static",
    entities=[account],
    ttl=timedelta(0),
    source=account_source,
    schema=[
        Field(name="account_frequency", dtype=String),
        Field(name="district_id", dtype=String),
        Field(name="district_name", dtype=String),
        Field(name="district_region", dtype=String),
        Field(name="district_population", dtype=Int64),
        Field(name="district_urban_ratio", dtype=Float64),
        Field(name="district_average_salary", dtype=Int64),
        Field(name="district_unemployment_1995", dtype=Float64),
        Field(name="district_unemployment_1996", dtype=Float64),
        Field(name="district_entrepreneurs_per_1000", dtype=Int64),
        Field(name="district_crimes_1995", dtype=Int64),
        Field(name="district_crimes_1996", dtype=Int64),
        Field(name="owner_client_id", dtype=String),
        Field(name="owner_gender", dtype=String),
        Field(name="owner_birth_date", dtype=UnixTimestamp),
        Field(name="owner_district_id", dtype=String),
        Field(name="dependent_count", dtype=Int64),
        Field(name="has_card", dtype=Bool),
        Field(name="card_type", dtype=String),
        Field(name="card_issued_date", dtype=UnixTimestamp),
        Field(name="has_loan", dtype=Bool),
        Field(name="loan_date", dtype=UnixTimestamp),
        Field(name="loan_amount", dtype=Float64),
        Field(name="loan_duration", dtype=Int64),
        Field(name="loan_payments", dtype=Float64),
        Field(name="loan_payment_ratio", dtype=Float64),
        Field(name="loan_status", dtype=String),
    ],
)

_INT_MONTHLY = [
    "account_age_months", "year", "month", "transaction_count", "active_days", "credit_transaction_count",
    "debit_transaction_count", "withdrawal_transaction_count", "transfer_transaction_count", "loan_payment_count",
    "transfer_out_count", "transfer_in_count", "cash_withdrawal_count", "card_withdrawal_count",
]  # fmt: skip
_FLOAT_MONTHLY = [
    "inflow_amount", "outflow_amount", "net_flow", "avg_transaction_amount", "min_transaction_amount",
    "max_transaction_amount", "opening_balance", "closing_balance", "avg_balance", "min_balance", "max_balance",
    "cash_withdrawal_amount", "card_withdrawal_amount", "transfer_out_amount", "transfer_in_amount",
    "loan_payment_amount", "insurance_payment_amount", "domestic_payment_amount", "interest_amount",
    "penalty_interest_amount", "previous_month_outflow", "previous_month_inflow", "outflow_3m_avg", "outflow_3m_sum",
    "outflow_6m_avg", "inflow_3m_avg", "avg_balance_3m", "transaction_count_3m_avg", "outflow_mom_change",
    "inflow_mom_change", "balance_mom_change",
]  # fmt: skip

# Mensal: `reference_month` (fim do mês) é o event_timestamp. Sem TTL: o TTL do offline store de
# arquivos (Dask) descarta a linha inteira quando a feature expira e quebra se todas expirarem.
# Quem monta o dataset de treino deve partir de pares (conta, mês) reais da Gold, nunca de datas
# arbitrárias depois do último mês da conta (a feature "vigente" seria a do último mês ativo).
account_monthly = FeatureView(
    name="account_monthly",
    entities=[account],
    ttl=timedelta(0),
    source=monthly_source,
    schema=[
        *(Field(name=n, dtype=Int64) for n in _INT_MONTHLY),
        *(Field(name=n, dtype=Float64) for n in _FLOAT_MONTHLY),
    ],
)

# Regressão de gastos do próximo mês (README, "Modelos Supervisionados"): só a visão mensal e o histórico.
# O target (`outflow_amount` do mês seguinte) NÃO é uma feature: é montado no dataset de treino.
outflow_regression = FeatureService(
    name="outflow_regression",
    features=[
        account_monthly[
            [
                "active_days", "inflow_amount", "outflow_amount", "net_flow", "transaction_count",
                "avg_transaction_amount", "max_transaction_amount", "opening_balance", "closing_balance",
                "avg_balance", "min_balance", "max_balance", "cash_withdrawal_amount", "card_withdrawal_amount",
                "transfer_out_amount", "loan_payment_amount", "insurance_payment_amount", "domestic_payment_amount",
                "previous_month_outflow", "previous_month_inflow", "outflow_3m_avg", "outflow_3m_sum",
                "outflow_6m_avg", "inflow_3m_avg", "avg_balance_3m", "transaction_count_3m_avg",
                "outflow_mom_change", "inflow_mom_change", "balance_mom_change",
            ]
        ]
    ],
)  # fmt: skip
