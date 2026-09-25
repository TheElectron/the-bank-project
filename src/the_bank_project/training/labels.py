"""Labels do modelo de regressão: `next_month_outflow = outflow_amount(T+1)`, por conta.

Fica fora do Feast de propósito: o label é o futuro, e a feature store só serve o
que era conhecido no instante consultado.
"""

import logging
from pathlib import Path

import pandas as pd

from the_bank_project.io import write_parquet_atomic

logger = logging.getLogger(__name__)

MONTHLY_TABLE = "gold_account_monthly_movements"
LABELS_TABLE = "labels_outflow"
TARGET = "next_month_outflow"


def build_labels(monthly: pd.DataFrame) -> pd.DataFrame:
    """`gold_account_monthly_movements` → labels (`account_id`, `event_timestamp`, `next_month_outflow`).

    `event_timestamp` é o `reference_month` de T (as features de T vêm do Feast nesse instante).
    O último mês de cada conta não tem T+1 e sai do resultado.

    Raises:
        ValueError: se a série de alguma conta não for mensal contígua (a Gold garante que é).
    """
    m = monthly[["account_id", "reference_month", "outflow_amount"]].sort_values(["account_id", "reference_month"])
    g = m.groupby("account_id")
    nxt_month, nxt_outflow = g["reference_month"].shift(-1), g["outflow_amount"].shift(-1)
    has_next = nxt_month.notna()
    if (nxt_month[has_next] != m.loc[has_next, "reference_month"] + pd.offsets.MonthEnd(1)).any():
        raise ValueError("Série mensal não contígua: o mês seguinte de alguma conta não é T+1.")
    labels = pd.DataFrame({
        "account_id": m.loc[has_next, "account_id"],
        "event_timestamp": m.loc[has_next, "reference_month"],
        TARGET: nxt_outflow[has_next].astype("float64"),
    })  # fmt: skip
    return labels.reset_index(drop=True)


def gold_to_labels(gold_dir: Path) -> Path:
    """Lê a Gold mensal e grava `labels_outflow.parquet` ao lado dela (idempotente).

    Raises:
        FileNotFoundError: se a Gold mensal não existir.
    """
    source = gold_dir / f"{MONTHLY_TABLE}.parquet"
    if not source.exists():
        raise FileNotFoundError(f"{source} não existe. Rode a Gold antes.")
    labels = build_labels(pd.read_parquet(source))
    target = write_parquet_atomic(labels, gold_dir / f"{LABELS_TABLE}.parquet")
    logger.info("%s -> %s (%d linhas)", MONTHLY_TABLE, target.name, len(labels))
    return target
