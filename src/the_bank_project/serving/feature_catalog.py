"""Nomes legíveis, agrupamento e unidade das features, para a interface.

Cada feature do FeatureService precisa constar aqui (há um teste de contrato).
"""

from typing import Literal

from pydantic import BaseModel

Unit = Literal["money", "count", "pct"]


class FeatureMeta(BaseModel):
    """Como mostrar uma feature ao usuário."""

    name: str
    label: str
    group: str
    unit: Unit
    help: str


MONTH, BALANCE, MIX, HISTORY = "Movimentação do mês", "Saldo", "Composição dos gastos", "Histórico e tendência"

_ROWS: list[tuple[str, str, str, Unit, str]] = [
    ("active_days", "Dias com movimento", MONTH, "count", "Quantos dias do mês tiveram ao menos uma transação."),
    ("transaction_count", "Nº de transações", MONTH, "count", "Total de transações no mês."),
    ("inflow_amount", "Entradas", MONTH, "money", "Total recebido no mês (créditos)."),
    ("outflow_amount", "Saídas", MONTH, "money", "Total debitado no mês (débitos e saques)."),
    ("net_flow", "Fluxo líquido", MONTH, "money", "Entradas menos saídas do mês."),
    ("avg_transaction_amount", "Valor médio por transação", MONTH, "money", "Média dos valores das transações do mês."),
    ("max_transaction_amount", "Maior transação", MONTH, "money", "Maior valor movimentado numa única transação."),
    ("opening_balance", "Saldo inicial (estimado)", BALANCE, "money", "Saldo antes da primeira transação do mês."),
    ("closing_balance", "Saldo final", BALANCE, "money", "Saldo após a última transação do mês."),
    ("avg_balance", "Saldo médio", BALANCE, "money", "Média do saldo observado nas transações do mês."),
    ("min_balance", "Menor saldo", BALANCE, "money", "Menor saldo observado no mês."),
    ("max_balance", "Maior saldo", BALANCE, "money", "Maior saldo observado no mês."),
    ("cash_withdrawal_amount", "Saques em dinheiro", MIX, "money", "Total sacado em dinheiro no mês."),
    ("card_withdrawal_amount", "Saques com cartão", MIX, "money", "Total sacado com cartão no mês."),
    ("transfer_out_amount", "Transferências enviadas", MIX, "money", "Total transferido para outros bancos."),
    ("loan_payment_amount", "Pagamento de empréstimo", MIX, "money", "Total pago em parcelas de empréstimo."),
    ("insurance_payment_amount", "Pagamento de seguro", MIX, "money", "Total pago em seguros."),
    ("domestic_payment_amount", "Pagamentos domésticos", MIX, "money", "Total em pagamentos domésticos."),
    ("previous_month_outflow", "Saídas do mês anterior", HISTORY, "money", "Saídas totais no mês anterior."),
    ("previous_month_inflow", "Entradas do mês anterior", HISTORY, "money", "Entradas totais no mês anterior."),
    ("outflow_3m_avg", "Saídas: média de 3 meses", HISTORY, "money", "Média mensal das saídas nos últimos 3 meses."),
    ("outflow_3m_sum", "Saídas: soma de 3 meses", HISTORY, "money", "Soma das saídas nos últimos 3 meses."),
    ("outflow_6m_avg", "Saídas: média de 6 meses", HISTORY, "money", "Média mensal das saídas nos últimos 6 meses."),
    ("inflow_3m_avg", "Entradas: média de 3 meses", HISTORY, "money", "Média mensal das entradas nos últimos 3 meses."),
    ("avg_balance_3m", "Saldo médio de 3 meses", HISTORY, "money", "Média do saldo médio nos últimos 3 meses."),
    ("transaction_count_3m_avg", "Transações/mês (3 meses)", HISTORY, "count", "Média mensal de transações (3 meses)."),
    ("outflow_mom_change", "Variação das saídas", HISTORY, "pct", "Saídas do mês contra o mês anterior."),
    ("inflow_mom_change", "Variação das entradas", HISTORY, "pct", "Entradas do mês contra o mês anterior."),
    ("balance_mom_change", "Variação do saldo", HISTORY, "money", "Saldo final do mês menos o do mês anterior."),
]  # fmt: skip

FEATURES: dict[str, FeatureMeta] = {
    name: FeatureMeta(name=name, label=label, group=group, unit=unit, help=help_)
    for name, label, group, unit, help_ in _ROWS
}
GROUPS = [MONTH, BALANCE, MIX, HISTORY]
