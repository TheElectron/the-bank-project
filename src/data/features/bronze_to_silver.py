#!/usr/bin/env python3
"""Lê a `bronze/` (cópia 1:1 da Raw, tudo `string`), trata tipos/nulos e grava o
resultado na `silver/`.

Diferente da Bronze, aqui os dados deixam de ser cópia fiel: colunas de ID
ficam como texto, quantitativas viram `int`/`float`, nulos são tratados
(mediana / `'DESCONHECIDO'`), `date` (YYMMDD) vira `datetime`, `client.
birth_number` é decomposto em `gender` + `birth_date`, e os valores
categóricos (originalmente em tcheco) são traduzidos para português.

Por fim, o schema original de 8 tabelas é reorganizado para simplificar os
relacionamentos e reduzir os joins nas etapas seguintes: `disp` + `card`
são consolidadas em `client`, `loan` em `account` (merges 1:1 validados
contra os dados reais — ver README), e `district` só tem as colunas
renomeadas. Resultado: 5 tabelas (`district`, `client`, `account`,
`order`, `trans`) em vez de 8.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.common import DATALAKE_DIR, configure_logging, run_cli

logger = configure_logging("bronze_to_silver")

BRONZE_DIR = DATALAKE_DIR / "bronze"
SILVER_DIR = DATALAKE_DIR / "silver"

# O dataset Berka é da década de 1990; datas em YYMMDD assumem século 19xx.
CENTURY_PREFIX = "19"

# Marcador de valor nulo/ausente para colunas de texto e ID.
NULL_FILL_VALUE = "DESCONHECIDO"

# Tradução dos códigos categóricos do Berka (originalmente em tcheco) para
# português: {tabela: {coluna: {valor_original: valor_traduzido}}}. Aplicada
# por último, sobre os valores já tipados/tratados. Tabelas/colunas fora
# deste mapeamento (ex.: client.gender, card.type) já são language-neutral.
CATEGORICAL_TRANSLATIONS: dict[str, dict[str, dict[str, str]]] = {
    "account": {
        "frequency": {
            "POPLATEK MESICNE": "MENSAL",
            "POPLATEK TYDNE": "SEMANAL",
            "POPLATEK PO OBRATU": "POR TRANSACAO",
        },
    },
    "disp": {
        "type": {
            "OWNER": "TITULAR",
            "DISPONENT": "DEPENDENTE",
        },
    },
    "trans": {
        "type": {
            "PRIJEM": "CREDITO",
            "VYDAJ": "DEBITO",
            "VYBER": "SAQUE",
        },
        "operation": {
            "VYBER": "SAQUE EM ESPECIE",
            "VKLAD": "DEPOSITO EM ESPECIE",
            "PREVOD Z UCTU": "TRANSFERENCIA RECEBIDA",
            "PREVOD NA UCET": "TRANSFERENCIA ENVIADA",
            "VYBER KARTOU": "SAQUE NO CARTAO",
        },
        "k_symbol": {
            "POJISTNE": "SEGURO",
            "SLUZBY": "TARIFA DE SERVICO",
            "UROK": "JUROS CREDITADOS",
            "SANKC. UROK": "JUROS PUNITIVOS",
            "SIPO": "CONTAS DOMESTICAS",
            "DUCHOD": "APOSENTADORIA",
            "UVER": "PAGAMENTO DE EMPRESTIMO",
        },
    },
    "order": {
        "k_symbol": {
            "POJISTNE": "SEGURO",
            "SIPO": "CONTAS DOMESTICAS",
            "UVER": "PAGAMENTO DE EMPRESTIMO",
            "LEASING": "ARRENDAMENTO",
        },
    },
    "loan": {
        "status": {
            # Códigos originais (letras, sem texto a "traduzir") adaptados
            # para rótulos descritivos em português.
            "A": "ENCERRADO ADIMPLENTE",
            "B": "ENCERRADO INADIMPLENTE",
            "C": "ATIVO ADIMPLENTE",
            "D": "ATIVO INADIMPLENTE",
        },
    },
}

# Colunas que não seguem a convenção "id"/"*_id" mas são identificadores:
# "account" (trans.csv, conta de contrapartida) e "a1" (district.csv — a
# mesma chave referenciada por account/client.district_id; sem este
# override viraria Int64 enquanto as FKs viram string, e o join quebraria).
KNOWN_ID_OVERRIDES = {"account", "a1"}
ID_NAME_SUFFIXES = ("_id", "_to")

# Colunas de data (YYMMDD) que não se chamam "date" — card.issued é a
# única data das 8 tabelas com nome próprio.
KNOWN_DATE_COLUMN_NAMES = {"date", "issued"}


def is_id_column(column_name: str) -> bool:
    """Identifica colunas de identificação pelo nome (mantidas como `string`)."""
    name = column_name.strip().lower()
    return name == "id" or name in KNOWN_ID_OVERRIDES or any(name.endswith(s) for s in ID_NAME_SUFFIXES)


def normalize_blank_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Substitui `""`, `" "` e `'?'` por `NaN` — sempre o 1º passo do tratamento.

    A Bronze guarda tudo como string, então um valor ausente vira `""`
    antes de qualquer conversão de tipo. `'?'` é o marcador de ausência
    do Berka original em `district.A12`/`A15`; confirmamos que não
    aparece em nenhuma outra coluna com outro significado.
    """
    return df.replace(r"^\s*$|^\s*\?\s*$", np.nan, regex=True)


def convert_yymmdd_to_datetime(series: pd.Series, century_prefix: str = CENTURY_PREFIX) -> pd.Series:
    """Converte uma coluna 'YYMMDD' para `datetime64` (assume século `century_prefix`).

    Aceita um sufixo após os 6 dígitos (ex.: `card.issued` vem como
    `"931107 00:00:00"` no CSV original) — só os 6 primeiros caracteres
    são considerados.
    """
    non_null_mask = series.notna()
    yymmdd_only = series.astype(str).str.strip().str.slice(0, 6)
    prefixed = series.where(~non_null_mask, century_prefix + yymmdd_only)
    return pd.to_datetime(prefixed, format="%Y%m%d", errors="coerce")


def derive_gender_and_birth_date(df: pd.DataFrame, century_prefix: str = CENTURY_PREFIX) -> pd.DataFrame:
    """Decompõe `client.birth_number` (YYMMDD, +50 no mês para mulheres) em `gender` + `birth_date`."""
    century_base = int(century_prefix) * 100

    def _parse(raw: object) -> tuple[object, pd.Timestamp]:
        if pd.isna(raw):
            return np.nan, pd.NaT
        raw_str = str(raw).strip()
        if len(raw_str) != 6 or not raw_str.isdigit():
            return np.nan, pd.NaT
        yy, mm, dd = int(raw_str[0:2]), int(raw_str[2:4]), int(raw_str[4:6])
        gender = "F" if mm > 50 else "M"
        if gender == "F":
            mm -= 50
        try:
            birth_date = pd.Timestamp(year=century_base + yy, month=mm, day=dd)
        except ValueError:
            birth_date = pd.NaT
        return gender, birth_date

    parsed = df["birth_number"].map(_parse)
    df = df.copy()
    df["gender"] = parsed.map(lambda t: t[0]).astype("string")
    df["birth_date"] = parsed.map(lambda t: t[1])
    df = df.drop(columns=["birth_number"])
    logger.info("  [client] 'birth_number' decomposta em 'gender' + 'birth_date'.")
    return df


def _try_parse_numeric(series: pd.Series) -> pd.Series | None:
    """Converte para float64 só se TODOS os valores não nulos forem numéricos; senão, `None`."""
    non_null = series.dropna()
    if non_null.empty or pd.to_numeric(non_null, errors="coerce").isna().any():
        return None
    return pd.to_numeric(series, errors="coerce")


def _is_integer_like(series: pd.Series) -> bool:
    """True se todos os valores não nulos (como texto original) forem inteiros puros (`-?\\d+`)."""
    non_null = series.dropna().astype(str).str.strip()
    return non_null.empty or bool(non_null.str.fullmatch(r"-?\d+").all())


def classify_and_convert_columns(df: pd.DataFrame, table_name: str) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Classifica e converte as colunas de uma tabela: id/data/numérica/categórica.

    Ordem: já `datetime64` (tratada antes, ex. `birth_date`) -> mantida;
    nome de ID -> `string`; nome em `KNOWN_DATE_COLUMN_NAMES` ->
    `datetime64`; 100% numérica -> `int`/`float`; caso contrário ->
    `string` (categórica).

    Returns:
        Tupla (DataFrame convertido, relatório `{categoria: [colunas]}`).
    """
    df = df.copy()
    report: dict[str, list[str]] = {"id": [], "date": [], "int": [], "float": [], "categorical": []}

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            report["date"].append(col)
        elif is_id_column(col):
            df[col] = df[col].astype("string")
            report["id"].append(col)
        elif col.strip().lower() in KNOWN_DATE_COLUMN_NAMES:
            df[col] = convert_yymmdd_to_datetime(df[col])
            report["date"].append(col)
        else:
            numeric_series = _try_parse_numeric(df[col])
            if numeric_series is not None:
                df[col] = numeric_series
                report["int" if _is_integer_like(df[col]) else "float"].append(col)
            else:
                df[col] = df[col].astype("string")
                report["categorical"].append(col)

    for category, cols in report.items():
        logger.info("  [%s] colunas (%s): %s", table_name, category, cols or "-")
    return df, report


def fill_missing_values(df: pd.DataFrame, report: dict[str, list[str]], table_name: str) -> pd.DataFrame:
    """Preenche nulos: mediana (numéricas), `NULL_FILL_VALUE` (texto/id); datas ficam `NaT`."""
    df = df.copy()

    for col in report["int"] + report["float"]:
        n_missing = int(df[col].isna().sum())
        if n_missing == 0:
            continue
        median_value = df[col].median()
        if pd.isna(median_value):
            logger.warning("  [%s] coluna '%s' inteiramente nula; mediana não calculável.", table_name, col)
            continue
        df[col] = df[col].fillna(median_value)
        logger.info("  [%s] '%s': %d nulo(s) preenchido(s) com a mediana (%.4f).", table_name, col, n_missing, median_value)

    for col in report["int"]:
        df[col] = df[col].round().astype("Int64")

    for col in report["categorical"] + report["id"]:
        n_missing = int(df[col].isna().sum())
        if n_missing:
            df[col] = df[col].fillna(NULL_FILL_VALUE)
            logger.info("  [%s] '%s': %d nulo(s) preenchido(s) com '%s'.", table_name, col, n_missing, NULL_FILL_VALUE)

    for col in report["date"]:
        n_missing = int(df[col].isna().sum())
        if n_missing:
            logger.warning("  [%s] '%s': %d data(s) ausente(s)/inválida(s) (NaT) não preenchida(s).", table_name, col, n_missing)

    return df


def translate_categorical_values(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Traduz os valores categóricos da tabela via `CATEGORICAL_TRANSLATIONS` (sem efeito se não mapeada)."""
    table_map = CATEGORICAL_TRANSLATIONS.get(table_name)
    if not table_map:
        return df

    df = df.copy()
    for column_name, value_map in table_map.items():
        if column_name not in df.columns:
            continue
        n_affected = int(df[column_name].isin(value_map.keys()).sum())
        if n_affected:
            df[column_name] = df[column_name].replace(value_map)
            logger.info("  [%s] '%s': %d valor(es) traduzido(s).", table_name, column_name, n_affected)
    return df


def process_table(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Aplica o pipeline Bronze -> Silver a uma tabela: normaliza, tipa, preenche nulos, traduz."""
    logger.info("Processando '%s' (%d linhas, %d colunas)...", table_name, *df.shape)
    df = normalize_blank_strings(df)
    if "birth_number" in df.columns:
        df = derive_gender_and_birth_date(df)
    df, report = classify_and_convert_columns(df, table_name)
    df = fill_missing_values(df, report, table_name)
    df = translate_categorical_values(df, table_name)
    logger.info("'%s' tratada com sucesso (%d linhas, %d colunas finais).", table_name, *df.shape)
    return df


# Reorganização do schema: `disp`+`card` -> `client`; `loan` -> `account`;
# `district` renomeada. Os 3 merges são 1:1 (nunca 1:N) — validado contra os
# dados reais (ver README): todo client tem exatamente 1 disp; todo card
# pertence a um disp TITULAR único; toda account tem no máximo 1 loan.
# `validate="one_to_one"` barra a gravação caso isso deixe de valer no futuro.
DISTRICT_COLUMN_RENAME: dict[str, str] = {
    "A1": "district_id",
    "A2": "district_name",
    "A3": "region",
    "A4": "population",
    "A5": "municipalities_under_499",
    "A6": "municipalities_500_1999",
    "A7": "municipalities_2000_9999",
    "A8": "municipalities_over_10000",
    "A9": "cities",
    "A10": "urban_population_ratio",
    "A11": "average_salary",
    "A12": "unemployment_rate_1995",
    "A13": "unemployment_rate_1996",
    "A14": "entrepreneurs_per_1000",
    "A15": "crimes_1995",
    "A16": "crimes_1996",
}


def rename_district_columns(district_df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia A1..A16 para nomes descritivos (dados inalterados)."""
    return district_df.rename(columns=DISTRICT_COLUMN_RENAME)


def build_client_table(client_df: pd.DataFrame, disp_df: pd.DataFrame, card_df: pd.DataFrame) -> pd.DataFrame:
    """Consolida `disp` (-> `account_id`/`relationship_type`) + `card` dentro de `client`."""
    disp_renamed = disp_df.rename(columns={"type": "relationship_type"})
    merged = client_df.merge(
        disp_renamed[["disp_id", "client_id", "account_id", "relationship_type"]],
        on="client_id", how="left", validate="one_to_one",
    )
    card_renamed = card_df.rename(columns={"type": "card_type", "issued": "card_issued"})
    merged = merged.merge(
        card_renamed[["disp_id", "card_id", "card_type", "card_issued"]],
        on="disp_id", how="left", validate="one_to_one",
    )
    # disp_id não é mantida: era só o artefato de join, redundante agora
    # que account_id é uma coluna direta de client.
    merged = merged.drop(columns=["disp_id"])
    return merged[["client_id", "account_id", "relationship_type", "district_id", "gender", "birth_date", "card_id", "card_type", "card_issued"]]


def build_account_table(account_df: pd.DataFrame, loan_df: pd.DataFrame) -> pd.DataFrame:
    """Consolida `loan` dentro de `account` (colunas com prefixo `loan_`, nulas se sem empréstimo)."""
    loan_renamed = loan_df.rename(columns={
        "date": "loan_date", "amount": "loan_amount", "duration": "loan_duration",
        "payments": "loan_payments", "status": "loan_status",
    })
    merged = account_df.merge(loan_renamed, on="account_id", how="left", validate="one_to_one")
    return merged[["account_id", "district_id", "frequency", "date", "loan_id", "loan_date", "loan_amount", "loan_duration", "loan_payments", "loan_status"]]


REQUIRED_SOURCE_TABLES = {"account", "card", "client", "disp", "district", "loan", "order", "trans"}

# Tabelas de uma execução anterior à reorganização, removidas se sobrarem.
STALE_SILVER_TABLES = {"disp", "card", "loan"}


def run(bronze_dir: Path = BRONZE_DIR, silver_dir: Path = SILVER_DIR) -> None:
    """Executa o pipeline Bronze -> Silver: trata as 8 tabelas e reorganiza em 5.

    Uma falha no tratamento de uma tabela é registrada mas não
    interrompe as demais; ao final, se houve alguma falha (ou faltar
    alguma tabela exigida pela reorganização), uma exceção é levantada.

    Raises:
        RuntimeError: falha no tratamento, ou tabela exigida ausente.
    """
    silver_dir.mkdir(parents=True, exist_ok=True)
    parquet_files = sorted(bronze_dir.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"Nenhum arquivo .parquet encontrado em {bronze_dir}. Execute raw_to_bronze.py antes.")

    processed: dict[str, pd.DataFrame] = {}
    failed: list[tuple[Path, Exception]] = []
    logger.info("Iniciando tratamento Bronze -> Silver (%d tabela(s))...", len(parquet_files))
    for parquet_path in parquet_files:
        table_name = parquet_path.stem
        try:
            processed[table_name] = process_table(pd.read_parquet(parquet_path), table_name)
        except Exception as exc:  # noqa: BLE001 - captura ampla e intencional: isola falhas por tabela
            logger.exception("Falha ao processar a tabela '%s'.", table_name)
            failed.append((parquet_path, exc))

    logger.info("Tratamento por tabela finalizado: %d sucesso(s), %d falha(s).", len(processed), len(failed))
    if failed:
        raise RuntimeError(f"Falha ao tratar {len(failed)} tabela(s): {', '.join(p.stem for p, _ in failed)}")

    faltantes = REQUIRED_SOURCE_TABLES - processed.keys()
    if faltantes:
        raise RuntimeError(f"Tabela(s) exigida(s) pela consolidação ausente(s) na Bronze: {sorted(faltantes)}.")

    logger.info("Consolidando: disp+card -> client, loan -> account, district renomeada...")
    final_tables = {
        "district": rename_district_columns(processed["district"]),
        "client": build_client_table(processed["client"], processed["disp"], processed["card"]),
        "account": build_account_table(processed["account"], processed["loan"]),
        "order": processed["order"],
        "trans": processed["trans"],
    }

    for stale_name in STALE_SILVER_TABLES:
        stale_path = silver_dir / f"{stale_name}.parquet"
        if stale_path.exists():
            stale_path.unlink()
            logger.info("  - removido arquivo obsoleto (pré-reorganização): %s", stale_path)

    for table_name, df in final_tables.items():
        out_path = silver_dir / f"{table_name}.parquet"
        df.to_parquet(out_path, engine="pyarrow", index=False)
        logger.info("  -> gravado: %s (%d linhas, %d colunas)", out_path, *df.shape)

    logger.info("Camada Silver (reorganizada, 5 tabelas) atualizada com sucesso em: %s", silver_dir)


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(description="Trata os .parquet da Bronze e grava o resultado na Silver.")
    parser.add_argument("--bronze-dir", default=str(BRONZE_DIR), help=f"Padrão: {BRONZE_DIR}.")
    parser.add_argument("--silver-dir", default=str(SILVER_DIR), help=f"Padrão: {SILVER_DIR}.")
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    return run_cli(lambda: run(Path(args.bronze_dir), Path(args.silver_dir)), logger)


if __name__ == "__main__":
    sys.exit(main())
