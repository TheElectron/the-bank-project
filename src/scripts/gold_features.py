#!/usr/bin/env python3
"""Gera a `gold/` a partir da `silver/`: feature store no grão `account_id` x
`ano_mes`, para a previsão de entradas mensais por conta (Proposta 2 — ver
README, seção "Modelagem da Gold").

Duas decisões evitam vazamento de informação do futuro: `loan_status`
(desfecho final do empréstimo) não é usado como feature — só
`loan_ativo_no_mes` (presença, um fato conhecido na época) e
`loan_payments` (valor fixo desde a concessão); mesma lógica para
`card_ativo_no_mes`. E o preenchimento de gaps mensais reindexa cada conta
para um calendário contínuo entre o primeiro e o último mês com QUALQUER
transação (não só crédito) — sem isso, `rolling`/`shift` operariam sobre
*linhas* em vez de meses de calendário.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from _common import DATALAKE_DIR, configure_logging, run_cli

logger = configure_logging("gold_features")

SILVER_DIR = DATALAKE_DIR / "silver"
GOLD_DIR = DATALAKE_DIR / "gold"

ROLLING_WINDOW_MONTHS = 3
DEBIT_TYPES = {"DEBITO", "SAQUE"}

DISTRICT_FEATURE_COLUMNS = [
    "average_salary", "unemployment_rate_1995", "unemployment_rate_1996", "population",
    "entrepreneurs_per_1000", "crimes_1995", "crimes_1996", "urban_population_ratio",
]


# 1) Leitura da Silver
def load_silver_tables(silver_dir: Path) -> dict[str, pd.DataFrame]:
    """Lê as 5 tabelas da Silver.

    Raises:
        FileNotFoundError: se alguma tabela esperada não existir.
    """
    tables = {}
    for name in ("district", "client", "account", "order", "trans"):
        path = silver_dir / f"{name}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"Tabela '{name}' não encontrada em {silver_dir}. Execute bronze_to_silver.py antes.")
        tables[name] = pd.read_parquet(path)
    logger.info("Silver carregada: %s", {k: v.shape for k, v in tables.items()})
    return tables


# 2) Features estáticas por conta (district + client + order, denormalizadas)
def build_account_static_features(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Monta 1 linha por conta com os atributos que não variam mês a mês.

    Inclui `loan_date`/`loan_duration`/`loan_payments`/`card_issued` ainda
    "crus" — viram `*_ativo_no_mes` depois, em `add_time_varying_flags`.
    """
    account, district, client, order = tables["account"], tables["district"], tables["client"], tables["order"]

    static = account.merge(district[["district_id"] + DISTRICT_FEATURE_COLUMNS], on="district_id", how="left")

    titular = client[client["relationship_type"] == "TITULAR"].set_index("account_id")
    static = static.merge(
        titular[["gender", "birth_date", "card_issued"]].rename(columns={"gender": "titular_gender", "birth_date": "titular_birth_date"}),
        on="account_id", how="left",
    )

    has_dependente = client.groupby("account_id")["relationship_type"].apply(lambda s: (s == "DEPENDENTE").any())
    static["has_dependente"] = static["account_id"].map(has_dependente).fillna(False)

    orders_sum = order.groupby("account_id")["amount"].sum()
    static["soma_orders_mensais"] = static["account_id"].map(orders_sum).fillna(0.0)

    logger.info("Features estáticas por conta montadas: %d contas, %d colunas.", *static.shape)
    return static


# 3) Agregados mensais de trans (entradas / saídas / saldo / contagem)
def build_monthly_trans_aggregates(trans: pd.DataFrame) -> pd.DataFrame:
    """Agrega `trans` por conta e mês (sem gap-fill ainda — ver `fill_monthly_gaps`)."""
    trans = trans.sort_values(["account_id", "date"]).copy()
    trans["ano_mes"] = trans["date"].dt.to_period("M")
    trans["_credit_amount"] = trans["amount"].where(trans["type"] == "CREDITO", 0.0)
    trans["_debit_amount"] = trans["amount"].where(trans["type"].isin(DEBIT_TYPES), 0.0)

    monthly = trans.groupby(["account_id", "ano_mes"], as_index=False).agg(
        soma_entradas_mes_atual=("_credit_amount", "sum"),
        soma_saidas_mes_atual=("_debit_amount", "sum"),
        saldo_fim_mes=("balance", "last"),
        n_transacoes_mes=("trans_id", "count"),
    )
    logger.info("Agregados mensais de trans: %d linhas conta-mês observadas (antes do gap-fill).", len(monthly))
    return monthly


# 4) Preenchimento de gaps mensais (calendário contínuo por conta)
def fill_monthly_gaps(monthly: pd.DataFrame) -> pd.DataFrame:
    """Reindexa cada conta para um calendário mensal contínuo.

    Meses sem transação: entradas/saídas/contagem viram 0; `saldo_fim_mes`
    é propagado (`ffill`) do último mês observado.
    """
    filled = []
    n_gaps = 0
    for account_id, group in monthly.groupby("account_id", sort=False):
        group = group.set_index("ano_mes").sort_index()
        full_range = pd.period_range(group.index.min(), group.index.max(), freq="M")
        n_gaps += len(full_range) - len(group)

        group = group.reindex(full_range)
        group.index.name = "ano_mes"
        group["account_id"] = account_id
        for col in ["soma_entradas_mes_atual", "soma_saidas_mes_atual", "n_transacoes_mes"]:
            group[col] = group[col].fillna(0.0)
        group["saldo_fim_mes"] = group["saldo_fim_mes"].ffill()
        filled.append(group.reset_index())

    result = pd.concat(filled, ignore_index=True)
    logger.info("Gaps mensais preenchidos: %d mês(es) adicionados (%d -> %d linhas).", n_gaps, len(monthly), len(result))
    return result


# 5) Flags/atributos dependentes do mês (loan/card ativos, idades, sazonalidade)
def add_time_varying_flags(monthly: pd.DataFrame, account_static: pd.DataFrame) -> pd.DataFrame:
    """Junta as features estáticas e deriva as que dependem do mês (idades, loan/card ativos, sazonalidade)."""
    df = monthly.merge(account_static, on="account_id", how="left")

    df["mes_do_ano"] = df["ano_mes"].dt.month
    df["account_age_months"] = (df["ano_mes"] - df["date"].dt.to_period("M")).apply(lambda offset: offset.n)
    df["titular_age_years"] = (df["ano_mes"].dt.to_timestamp() - df["titular_birth_date"]).dt.days / 365.25

    loan_start = df["loan_date"].dt.to_period("M")
    # fillna(0) é seguro: onde loan_duration é nulo, loan_start já é NaT
    # (sem empréstimo) — NaT + 0 continua NaT, propagando corretamente.
    loan_end = loan_start + df["loan_duration"].fillna(0).astype("int64")
    df["loan_ativo_no_mes"] = ((df["ano_mes"] >= loan_start) & (df["ano_mes"] <= loan_end)).fillna(False)
    df.loc[~df["loan_ativo_no_mes"], "loan_payments"] = np.nan

    card_start = df["card_issued"].dt.to_period("M")
    df["card_ativo_no_mes"] = (df["ano_mes"] >= card_start).fillna(False)

    logger.info("Atributos dependentes do mês calculados (idade da conta/titular, loan/card ativos, sazonalidade).")
    return df


# 6) Janela móvel de 3 meses + target (próximo mês)
def add_rolling_features_and_target(df: pd.DataFrame, window: int = ROLLING_WINDOW_MONTHS) -> pd.DataFrame:
    """Calcula as features de janela móvel e o target (entradas do mês seguinte).

    A janela usa dado até e incluindo o mês atual (sem olhar o futuro); o
    target usa `shift(-1)` por conta — por isso as bordas de cada conta
    (início: sem janela completa; fim: sem mês seguinte) ficam incompletas
    e são removidas depois (ver `drop_incomplete_rows`).
    """
    df = df.sort_values(["account_id", "ano_mes"]).copy()
    entradas = df.groupby("account_id")["soma_entradas_mes_atual"]
    saidas = df.groupby("account_id")["soma_saidas_mes_atual"]

    df["media_entradas_ultimos_3_meses"] = entradas.transform(lambda s: s.rolling(window, min_periods=window).mean())
    df["desvio_padrao_entradas_ultimos_3_meses"] = entradas.transform(lambda s: s.rolling(window, min_periods=window).std())
    df["media_saidas_ultimos_3_meses"] = saidas.transform(lambda s: s.rolling(window, min_periods=window).mean())
    df["target_soma_entradas_proximo_mes"] = df.groupby("account_id")["soma_entradas_mes_atual"].shift(-1)

    logger.info("Features de janela móvel (%d meses) e target calculados.", window)
    return df


# 7) Remoção das linhas incompletas de borda
def drop_incomplete_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove linhas sem janela móvel completa ou sem mês seguinte (target)."""
    before = len(df)
    df = df.dropna(subset=["media_entradas_ultimos_3_meses", "desvio_padrao_entradas_ultimos_3_meses", "target_soma_entradas_proximo_mes"])
    logger.info("Linhas de borda removidas: %d -> %d.", before, len(df))
    return df


FINAL_COLUMNS = [
    "account_id", "ano_mes", "district_id", "frequency",
    "average_salary", "unemployment_rate_1995", "unemployment_rate_1996", "population",
    "entrepreneurs_per_1000", "crimes_1995", "crimes_1996", "urban_population_ratio",
    "titular_gender", "titular_age_years", "has_dependente", "soma_orders_mensais",
    "account_age_months", "loan_ativo_no_mes", "loan_payments", "card_ativo_no_mes", "mes_do_ano",
    "soma_entradas_mes_atual", "soma_saidas_mes_atual", "saldo_fim_mes", "n_transacoes_mes",
    "media_entradas_ultimos_3_meses", "desvio_padrao_entradas_ultimos_3_meses", "media_saidas_ultimos_3_meses",
    "target_soma_entradas_proximo_mes",
]


def run(silver_dir: Path = SILVER_DIR, gold_dir: Path = GOLD_DIR) -> None:
    """Executa o pipeline Silver -> Gold e grava `account_monthly_features.parquet`."""
    gold_dir.mkdir(parents=True, exist_ok=True)

    tables = load_silver_tables(silver_dir)
    account_static = build_account_static_features(tables)
    monthly = fill_monthly_gaps(build_monthly_trans_aggregates(tables["trans"]))
    df = add_time_varying_flags(monthly, account_static)
    df = add_rolling_features_and_target(df)
    df = drop_incomplete_rows(df)

    df["ano_mes"] = df["ano_mes"].dt.to_timestamp()
    df["n_transacoes_mes"] = df["n_transacoes_mes"].astype("Int64")
    df = df[FINAL_COLUMNS].sort_values(["account_id", "ano_mes"]).reset_index(drop=True)

    out_path = gold_dir / "account_monthly_features.parquet"
    df.to_parquet(out_path, engine="pyarrow", index=False)
    logger.info("Gravado: %s (%d linhas, %d colunas)", out_path, *df.shape)
    target = df["target_soma_entradas_proximo_mes"]
    logger.info("Target — min=%.2f mediana=%.2f média=%.2f max=%.2f", target.min(), target.median(), target.mean(), target.max())
    logger.info("Camada Gold atualizada com sucesso em: %s", gold_dir)


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(description="Gera datalake/gold/account_monthly_features.parquet a partir da Silver.")
    parser.add_argument("--silver-dir", default=str(SILVER_DIR), help=f"Padrão: {SILVER_DIR}.")
    parser.add_argument("--gold-dir", default=str(GOLD_DIR), help=f"Padrão: {GOLD_DIR}.")
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    return run_cli(lambda: run(Path(args.silver_dir), Path(args.gold_dir)), logger)


if __name__ == "__main__":
    sys.exit(main())
