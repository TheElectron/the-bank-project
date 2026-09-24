"""Silver → Gold: `build_gold` (puro) + `silver_to_gold` (I/O)."""

import logging
from pathlib import Path

import pandas as pd

from the_bank_project.gold.account import build_gold_account
from the_bank_project.gold.checks import check_gold
from the_bank_project.gold.monthly import build_gold_account_monthly
from the_bank_project.io import write_parquet_atomic

logger = logging.getLogger(__name__)

SILVER_TABLES = ("account", "client", "district", "trans")
GOLD_TABLES = ("gold_account", "gold_account_monthly_movements")


def build_gold(silver: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Função pura: Silver → as 2 tabelas da Gold, já validadas por `check_gold`."""
    account = build_gold_account(silver["account"], silver["client"], silver["district"])
    monthly = build_gold_account_monthly(silver["trans"], silver["account"])
    check_gold(account, monthly, silver["account"])
    return {"gold_account": account, "gold_account_monthly_movements": monthly}


def silver_to_gold(silver_dir: Path, gold_dir: Path) -> list[Path]:
    """Lê a Silver, constrói e valida a Gold e grava um parquet por tabela (idempotente).

    Nada é gravado se a validação falhar.

    Raises:
        FileNotFoundError: se faltar algum parquet da Silver.
    """
    missing = [t for t in SILVER_TABLES if not (silver_dir / f"{t}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"Faltam em {silver_dir}: {missing}. Rode a Silver antes.")
    gold = build_gold({t: pd.read_parquet(silver_dir / f"{t}.parquet") for t in SILVER_TABLES})
    paths = []
    for name in GOLD_TABLES:
        paths.append(write_parquet_atomic(gold[name], gold_dir / f"{name}.parquet"))
        logger.info("%s -> %s (%d linhas, %d colunas)", name, paths[-1].name, *gold[name].shape)
    return paths
