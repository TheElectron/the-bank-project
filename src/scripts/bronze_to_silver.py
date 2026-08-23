#!/usr/bin/env python3
"""
bronze_to_silver.py
====================

Lê os dados da camada `bronze/` (cópia 1:1 da Raw, tudo em `string`),
aplica o tratamento de tipos/nulos e grava o resultado na camada
`silver/real/` do Datalake (arquitetura Medallion).

Diferente da Bronze, aqui os dados deixam de ser uma cópia fiel e passam
a receber as primeiras regras de negócio/qualidade:
  - Colunas de identificação (`id` / `*_id`) permanecem como texto.
  - Colunas quantitativas são convertidas para `int`/`float`.
  - Nulos são tratados (mediana para numéricas, 'DESCONHECIDO' para texto).
  - A coluna `date` (formato `YYMMDD`, década de 1990) vira `datetime`.
  - Regra específica da tabela `client`: `birth_number` é decomposto em
    `gender` + `birth_date`.
  - Valores categóricos originalmente em tcheco (códigos do dataset Berka)
    são traduzidos/adaptados para português brasileiro.

--------------------------------------------------------------------------
PRÉ-REQUISITOS
--------------------------------------------------------------------------
1) Ambiente virtual ativo com as dependências instaladas:

     source .venv/bin/activate
     pip install -r requirements.txt

2) A camada `datalake/bronze/` já populada (ver `raw_to_bronze.py`).

3) Executar:

     python src/scripts/bronze_to_silver.py

--------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuração de logging (nível INFO conforme solicitado)
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bronze_to_silver")

# --------------------------------------------------------------------------
# Constantes globais
# --------------------------------------------------------------------------
# O script vive em <raiz>/src/scripts/; subimos dois níveis para achar a
# raiz do projeto e, a partir dela, localizar o datalake/.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT / "datalake"

BRONZE_DIR = BASE_DIR / "bronze"
SILVER_REAL_DIR = BASE_DIR / "silver" / "real"

# O dataset Berka é da década de 1990; datas em YYMMDD assumem século 19xx.
CENTURY_PREFIX = "19"

# Marcador de valor nulo/ausente para colunas de texto e ID (em português,
# para manter consistência com a tradução dos demais valores categóricos).
NULL_FILL_VALUE = "DESCONHECIDO"

# Tradução/adaptação dos códigos categóricos do dataset Berka (originalmente
# em tcheco) para português brasileiro: {tabela: {coluna: {valor_original:
# valor_traduzido}}}. Aplicada como último passo do tratamento, sobre os
# valores já tipados/tratados. Colunas/tabelas fora deste mapeamento (ex.:
# client.gender, card.type) permanecem como estão — já são valores
# language-neutral (M/F) ou termos já correntes em português (classic/gold).
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
            # Códigos originais de status de contrato (sem texto a
            # "traduzir" literalmente, apenas letras) adaptados para
            # rótulos descritivos em português.
            "A": "ENCERRADO ADIMPLENTE",
            "B": "ENCERRADO INADIMPLENTE",
            "C": "ATIVO ADIMPLENTE",
            "D": "ATIVO INADIMPLENTE",
        },
    },
}


# --------------------------------------------------------------------------
# 1) Descoberta dos arquivos .parquet na camada Bronze
# --------------------------------------------------------------------------
def find_parquet_files(bronze_dir: Path) -> list[Path]:
    """Lista todos os arquivos `.parquet` disponíveis na camada Bronze.

    Args:
        bronze_dir: diretório `datalake/bronze/`.

    Returns:
        Lista ordenada de caminhos para os arquivos .parquet encontrados.

    Raises:
        FileNotFoundError: se o diretório não existir ou estiver vazio.
    """
    if not bronze_dir.is_dir():
        raise FileNotFoundError(
            f"Diretório da camada Bronze não encontrado: {bronze_dir}. "
            "Execute raw_to_bronze.py antes."
        )

    parquet_files = sorted(p for p in bronze_dir.glob("*.parquet") if p.is_file())
    if not parquet_files:
        raise FileNotFoundError(f"Nenhum arquivo .parquet encontrado em {bronze_dir}.")

    logger.info("Encontradas %d tabela(s) .parquet em %s.", len(parquet_files), bronze_dir)
    return parquet_files


# --------------------------------------------------------------------------
# 2) Normalização de strings vazias -> NaN (primeiro passo, antes de tudo)
# --------------------------------------------------------------------------
def normalize_blank_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Substitui strings vazias/só-espaço (e o marcador `'?'`) por `np.nan`.

    Este é sempre o primeiro passo do tratamento: como a Bronze guarda
    tudo como string, um campo "ausente" no CSV original pode aparecer
    como `""` ou `" "`. Precisamos normalizar isso para `NaN` antes de
    qualquer inferência/conversão de tipo, senão essas strings seriam
    tratadas como valores válidos (ex.: viram uma categoria própria, ou
    quebram a conversão numérica).

    Também tratamos `'?'` como nulo: é o marcador de ausência usado pelo
    dataset Berka original em `district.A12`/`A15` (taxa de desemprego e
    criminalidade não disponíveis para o distrito de Praga em 1995/96).
    Confirmamos, ao inspecionar a Bronze inteira, que `'?'` não aparece em
    nenhuma outra coluna com outro significado — por isso é seguro tratá-lo
    como nulo de forma genérica, e não apenas nessas duas colunas.

    Args:
        df: DataFrame recém-lido da Bronze (todas as colunas string).

    Returns:
        Uma cópia do DataFrame com `""`, `" "` (e variações só de espaço)
        e `'?'` substituídos por `np.nan`.
    """
    # '^\s*$'      -> string vazia ou composta só por espaços/tabs.
    # '^\s*\?\s*$' -> apenas o caractere '?' (com espaços opcionais ao redor).
    return df.replace(r"^\s*$|^\s*\?\s*$", np.nan, regex=True)


# --------------------------------------------------------------------------
# 3) Identificação de colunas de ID
# --------------------------------------------------------------------------
# Colunas que não seguem a convenção "id"/"*_id", mas que representam
# identificadores/referências (e não quantidades) segundo o dicionário de
# dados do Berka. Descobertas ao inspecionar a Bronze: por serem
# compostas só de dígitos, seriam erroneamente tratadas como numéricas
# pela heurística de nome padrão.
#   - "account" (trans.csv): número da conta de contrapartida da transação.
#   - "a1" (district.csv): district_id da própria tabela district — é a
#     mesma chave referenciada por account.district_id/client.district_id
#     (ambas convertidas para string pela regra "*_id"). Sem este override,
#     A1 virava Int64 enquanto as FKs viravam string, e qualquer join
#     district <-> account/client quebrava por incompatibilidade de tipo.
KNOWN_ID_OVERRIDES = {"account", "a1"}

# Sufixos adicionais que também identificam referências/contrapartes,
# além do já esperado "_id" (ex.: order.account_to, order.bank_to).
ID_NAME_SUFFIXES = ("_id", "_to")

# Colunas que representam datas (formato YYMMDD) mas não se chamam "date".
# Descoberta ao inspecionar a Bronze: card.issued é a única data das 8
# tabelas com nome próprio; sem este override ela cai no ramo categórico
# e fica como texto cru (incluindo o sufixo " 00:00:00" já vindo do CSV
# original), em vez de datetime64 como as demais colunas de data.
KNOWN_DATE_COLUMN_NAMES = {"date", "issued"}


def is_id_column(column_name: str) -> bool:
    """Identifica colunas de identificação pelo nome.

    Regra: o nome (case-insensitive) é "id", termina em "_id"/"_to", ou
    está na lista explícita `KNOWN_ID_OVERRIDES` (identificadores do
    Berka que não seguem nenhuma convenção de sufixo — inclui `A1` de
    `district`, cujo nome genérico não bate com nenhum padrão de sufixo).

    Args:
        column_name: nome da coluna a avaliar.

    Returns:
        True se a coluna deve ser tratada como identificador (string).
    """
    name = column_name.strip().lower()
    if name == "id" or name in KNOWN_ID_OVERRIDES:
        return True
    return any(name.endswith(suffix) for suffix in ID_NAME_SUFFIXES)


# --------------------------------------------------------------------------
# 4) Conversão de datas YYMMDD -> datetime
# --------------------------------------------------------------------------
def convert_yymmdd_to_datetime(series: pd.Series, century_prefix: str = CENTURY_PREFIX) -> pd.Series:
    """Converte uma coluna de strings 'YYMMDD' para `datetime64`.

    Assume que todas as datas pertencem ao século informado por
    `century_prefix` (o dataset Berka é inteiramente da década de 1990,
    logo `'930101'` -> `01/01/1993`).

    Args:
        series: coluna de strings no formato YYMMDD (pode conter NaN).
            Aceita um sufixo extra após os 6 dígitos (ex.: `card.issued`
            vem como `"931107 00:00:00"` no CSV original) — apenas os 6
            primeiros caracteres são considerados, o restante é ignorado.
        century_prefix: prefixo de século a concatenar (padrão: "19").

    Returns:
        Série `datetime64[ns]`; valores inválidos/ausentes viram `NaT`.
    """
    non_null_mask = series.notna()
    yymmdd_only = series.astype(str).str.strip().str.slice(0, 6)
    prefixed = series.where(~non_null_mask, century_prefix + yymmdd_only)
    return pd.to_datetime(prefixed, format="%Y%m%d", errors="coerce")


# --------------------------------------------------------------------------
# 5) Regra específica da tabela 'client': birth_number -> gender + birth_date
# --------------------------------------------------------------------------
def derive_gender_and_birth_date(df: pd.DataFrame, century_prefix: str = CENTURY_PREFIX) -> pd.DataFrame:
    """Decompõe `birth_number` (YYMMDD, com +50 no mês para mulheres).

    Regra do dataset Berka: `birth_number` é a data de nascimento no
    formato YYMMDD, mas para clientes do sexo feminino o componente do
    mês recebe um acréscimo de 50 (ex.: mês 58 -> mês 08 + gênero 'F').

    Cria as colunas `gender` ('M'/'F') e `birth_date` (`datetime64`), e
    remove a coluna original `birth_number`.

    Args:
        df: DataFrame da tabela `client` (após `normalize_blank_strings`).
        century_prefix: prefixo de século usado para montar o ano cheio.

    Returns:
        Cópia do DataFrame com `birth_number` substituída por `gender` e
        `birth_date`.
    """
    century_base = int(century_prefix) * 100  # ex.: "19" -> 1900

    def _parse(raw: object) -> tuple[object, pd.Timestamp]:
        if pd.isna(raw):
            return np.nan, pd.NaT

        raw_str = str(raw).strip()
        if len(raw_str) != 6 or not raw_str.isdigit():
            return np.nan, pd.NaT

        yy, mm, dd = int(raw_str[0:2]), int(raw_str[2:4]), int(raw_str[4:6])
        gender = "M"
        if mm > 50:
            gender = "F"
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

    logger.info(
        "  [client] coluna 'birth_number' decomposta em 'gender' (M/F) + "
        "'birth_date' (datetime); coluna original removida."
    )
    return df


# --------------------------------------------------------------------------
# 6) Classificação e conversão de tipos das demais colunas
# --------------------------------------------------------------------------
def _try_parse_numeric(series: pd.Series) -> pd.Series | None:
    """Tenta converter uma coluna de strings para numérico (float64).

    Só considera a coluna "quantitativa" se TODOS os valores não nulos
    forem numericamente válidos. Se qualquer valor não nulo falhar, a
    coluna é considerada categórica/texto (retorna None) — evita que uma
    coluna majoritariamente numérica, mas com algum código textual, seja
    corrompida por uma conversão parcial (`errors='coerce'` silencioso).

    Args:
        series: coluna de strings (pode conter NaN).

    Returns:
        Série convertida (float64, preservando NaN) ou `None` se a coluna
        não for puramente numérica.
    """
    non_null = series.dropna()
    if non_null.empty:
        return None  # sem dado suficiente para inferir: mantém como texto

    if pd.to_numeric(non_null, errors="coerce").isna().any():
        return None  # existe valor não numérico -> não é quantitativa

    return pd.to_numeric(series, errors="coerce")


def _is_integer_like(series: pd.Series) -> bool:
    """Verifica (pelos valores originais em string) se a coluna é inteira.

    Usamos o texto original (e não o valor numérico já convertido) para
    decidir int vs. float: "700.00" deve permanecer float mesmo sem parte
    fracionária relevante, pois o formato de origem já indica que o campo
    é monetário/decimal por natureza.

    Args:
        series: coluna de strings (pode conter NaN).

    Returns:
        True se todos os valores não nulos forem inteiros "puros"
        (sem ponto decimal), no formato `-?\\d+`.
    """
    non_null = series.dropna().astype(str).str.strip()
    if non_null.empty:
        return True
    return bool(non_null.str.fullmatch(r"-?\d+").all())


def classify_and_convert_columns(df: pd.DataFrame, table_name: str) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Classifica e converte as colunas de uma tabela (exceto as já tratadas).

    Para cada coluna (que ainda não seja `datetime64`, já tratada por uma
    regra específica como `birth_date`):
      - Nome "id" ou "*_id"  -> mantida como `string`.
      - Nome em `KNOWN_DATE_COLUMN_NAMES` ("date", "issued") -> convertida
        para `datetime64` (YYMMDD).
      - Demais, se 100% numéricas -> convertidas para `int`/`float`.
      - Caso contrário        -> mantida como `string` (categórica).

    Args:
        df: DataFrame já com strings vazias normalizadas para NaN (e, se
            aplicável, já com a regra do `client` aplicada).
        table_name: nome lógico da tabela, usado apenas para logging.

    Returns:
        Tupla (DataFrame com colunas convertidas, relatório de
        classificação por categoria: {"id", "date", "int", "float",
        "categorical"} -> lista de nomes de coluna).
    """
    df = df.copy()
    report: dict[str, list[str]] = {"id": [], "date": [], "int": [], "float": [], "categorical": []}

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            # Já tratada por uma regra específica (ex.: 'birth_date').
            report["date"].append(col)
            continue

        if is_id_column(col):
            df[col] = df[col].astype("string")
            report["id"].append(col)
            continue

        if col.strip().lower() in KNOWN_DATE_COLUMN_NAMES:
            df[col] = convert_yymmdd_to_datetime(df[col])
            report["date"].append(col)
            continue

        numeric_series = _try_parse_numeric(df[col])
        if numeric_series is not None:
            is_int = _is_integer_like(df[col])
            df[col] = numeric_series
            report["int" if is_int else "float"].append(col)
        else:
            df[col] = df[col].astype("string")
            report["categorical"].append(col)

    logger.info("  [%s] colunas de ID (string): %s", table_name, report["id"] or "-")
    logger.info("  [%s] colunas de data (datetime): %s", table_name, report["date"] or "-")
    logger.info("  [%s] colunas numéricas (int): %s", table_name, report["int"] or "-")
    logger.info("  [%s] colunas numéricas (float): %s", table_name, report["float"] or "-")
    logger.info("  [%s] colunas categóricas/texto: %s", table_name, report["categorical"] or "-")

    return df, report


# --------------------------------------------------------------------------
# 7) Tratamento de nulos (mediana / NULL_FILL_VALUE)
# --------------------------------------------------------------------------
def fill_missing_values(df: pd.DataFrame, report: dict[str, list[str]], table_name: str) -> pd.DataFrame:
    """Preenche valores nulos conforme o tipo da coluna.

      - Numéricas (`int`/`float`): preenchidas com a **mediana** da coluna.
      - Texto/categóricas (inclui `id`): preenchidas com a string
        `NULL_FILL_VALUE` ('DESCONHECIDO').
      - Datas: não são preenchidas (não há um valor "neutro" razoável);
        apenas registramos um aviso caso existam nulos (`NaT`).

    Args:
        df: DataFrame já com os tipos corrigidos (`classify_and_convert_columns`).
        report: relatório de classificação retornado por
            `classify_and_convert_columns`.
        table_name: nome lógico da tabela, usado apenas para logging.

    Returns:
        DataFrame com os nulos tratados e as colunas inteiras já no dtype
        final (nullable `Int64`).
    """
    df = df.copy()

    # --- Numéricas: mediana ------------------------------------------------
    for col in report["int"] + report["float"]:
        n_missing = int(df[col].isna().sum())
        if n_missing == 0:
            continue

        median_value = df[col].median()
        if pd.isna(median_value):
            # Coluna inteiramente nula: não há mediana calculável.
            logger.warning(
                "  [%s] coluna '%s' está inteiramente nula; mediana não pôde ser calculada.",
                table_name,
                col,
            )
            continue

        df[col] = df[col].fillna(median_value)
        logger.info(
            "  [%s] coluna '%s': %d valor(es) nulo(s) preenchido(s) com a mediana (%.4f).",
            table_name,
            col,
            n_missing,
            median_value,
        )

    # Cast final das colunas inteiras. Usamos o dtype nullable "Int64" (e
    # não o "int64" padrão do NumPy) para não quebrar caso ainda reste
    # algum NaN (coluna inteiramente nula, tratada acima).
    for col in report["int"]:
        df[col] = df[col].round().astype("Int64")

    # --- Texto/categóricas (inclui IDs): NULL_FILL_VALUE --------------------
    for col in report["categorical"] + report["id"]:
        n_missing = int(df[col].isna().sum())
        if n_missing == 0:
            continue
        df[col] = df[col].fillna(NULL_FILL_VALUE)
        logger.info(
            "  [%s] coluna '%s': %d valor(es) nulo(s) preenchido(s) com '%s'.",
            table_name,
            col,
            n_missing,
            NULL_FILL_VALUE,
        )

    # --- Datas: apenas avisa, não preenche ---------------------------------
    for col in report["date"]:
        n_missing = int(df[col].isna().sum())
        if n_missing:
            logger.warning(
                "  [%s] coluna '%s': %d valor(es) de data ausente(s)/inválido(s) (NaT) não preenchido(s).",
                table_name,
                col,
                n_missing,
            )

    return df


# --------------------------------------------------------------------------
# 8) Tradução/adaptação dos valores categóricos para português brasileiro
# --------------------------------------------------------------------------
def translate_categorical_values(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Traduz/adapta para português brasileiro os valores categóricos da tabela.

    Usa o mapeamento declarado em `CATEGORICAL_TRANSLATIONS`. Só afeta
    tabelas/colunas presentes no mapeamento; qualquer valor não mapeado
    (incluindo `NULL_FILL_VALUE` e códigos eventualmente não previstos)
    passa inalterado — a tradução nunca derruba uma linha nem introduz
    nulo novo.

    Args:
        df: DataFrame já tipado e com nulos tratados
            (`classify_and_convert_columns` + `fill_missing_values`).
        table_name: nome lógico da tabela, usado para localizar o
            mapeamento e para logging.

    Returns:
        DataFrame com os valores categóricos traduzidos (cópia).
    """
    table_map = CATEGORICAL_TRANSLATIONS.get(table_name)
    if not table_map:
        return df

    df = df.copy()
    for column_name, value_map in table_map.items():
        if column_name not in df.columns:
            continue
        n_affected = int(df[column_name].isin(value_map.keys()).sum())
        if n_affected == 0:
            continue
        df[column_name] = df[column_name].replace(value_map)
        logger.info(
            "  [%s] coluna '%s': %d valor(es) traduzido(s) para português (%s).",
            table_name,
            column_name,
            n_affected,
            ", ".join(sorted(set(value_map.values()))),
        )

    return df


# --------------------------------------------------------------------------
# Orquestração por tabela
# --------------------------------------------------------------------------
def process_table(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Aplica o pipeline completo Bronze -> Silver/real a uma única tabela.

    Ordem das etapas:
      1. Normaliza strings vazias/só-espaço para NaN.
      2. [se aplicável] decompõe `birth_number` em `gender` + `birth_date`.
      3. Classifica e converte colunas (ID/data/numérica/categórica).
      4. Preenche nulos (mediana / `NULL_FILL_VALUE`).
      5. Traduz/adapta valores categóricos para português brasileiro.

    Args:
        df: DataFrame lido diretamente do .parquet da Bronze (tudo string).
        table_name: nome lógico da tabela (usado para logging).

    Returns:
        DataFrame tratado, pronto para ser gravado na Silver/real.
    """
    n_rows, n_cols = df.shape
    logger.info("Processando tabela '%s' (%d linhas, %d colunas)...", table_name, n_rows, n_cols)

    df = normalize_blank_strings(df)

    if "birth_number" in df.columns:
        df = derive_gender_and_birth_date(df)

    df, report = classify_and_convert_columns(df, table_name)
    df = fill_missing_values(df, report, table_name)
    df = translate_categorical_values(df, table_name)

    n_rows, n_cols = df.shape
    logger.info("Tabela '%s' tratada com sucesso (%d linhas, %d colunas finais).", table_name, n_rows, n_cols)
    return df


# --------------------------------------------------------------------------
# Orquestração geral
# --------------------------------------------------------------------------
def run(bronze_dir: Path = BRONZE_DIR, silver_dir: Path = SILVER_REAL_DIR) -> None:
    """Executa o pipeline completo Bronze -> Silver/real para todas as tabelas.

    Cada tabela é processada de forma independente: uma falha em uma
    tabela é registrada no log, mas não interrompe o processamento das
    demais. Ao final, se houver qualquer falha, uma exceção é levantada
    para sinalizar o erro ao chamador (código de saída != 0).

    Args:
        bronze_dir: diretório de origem (datalake/bronze/).
        silver_dir: diretório de destino (datalake/silver/real/).

    Raises:
        RuntimeError: se uma ou mais tabelas falharem no tratamento.
    """
    silver_dir.mkdir(parents=True, exist_ok=True)

    parquet_files = find_parquet_files(bronze_dir)

    succeeded: list[Path] = []
    failed: list[tuple[Path, Exception]] = []

    logger.info("Iniciando tratamento Bronze -> Silver/real (%d tabela(s))...", len(parquet_files))
    for parquet_path in parquet_files:
        table_name = parquet_path.stem
        try:
            df = pd.read_parquet(parquet_path)
            df = process_table(df, table_name)

            out_path = silver_dir / f"{table_name}.parquet"
            df.to_parquet(out_path, engine="pyarrow", index=False)
            logger.info("  -> gravado em: %s", out_path)
            succeeded.append(out_path)
        except Exception as exc:  # noqa: BLE001 - captura ampla e intencional: isola falhas por tabela
            logger.exception("Falha ao processar a tabela '%s'.", table_name)
            failed.append((parquet_path, exc))

    logger.info("Tratamento finalizado: %d sucesso(s), %d falha(s).", len(succeeded), len(failed))

    if failed:
        nomes = ", ".join(p.stem for p, _ in failed)
        raise RuntimeError(f"Falha ao tratar {len(failed)} tabela(s): {nomes}")

    logger.info("Camada Silver/real atualizada com sucesso em: %s", silver_dir)


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(
        description="Trata os .parquet da camada Bronze e grava o resultado na Silver/real."
    )
    parser.add_argument(
        "--bronze-dir",
        default=str(BRONZE_DIR),
        help=f"Diretório de origem dos .parquet (padrão: {BRONZE_DIR}).",
    )
    parser.add_argument(
        "--silver-dir",
        default=str(SILVER_REAL_DIR),
        help=f"Diretório de destino dos .parquet tratados (padrão: {SILVER_REAL_DIR}).",
    )
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    try:
        run(bronze_dir=Path(args.bronze_dir), silver_dir=Path(args.silver_dir))
    except Exception as exc:  # noqa: BLE001 - captura ampla e intencional no nível mais alto
        logger.error("Falha na execução do script: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
