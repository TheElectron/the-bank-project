#!/usr/bin/env python3
"""Treina e valida o modelo de previsão de entradas mensais por conta
(Proposta 2 — ver README, seção "Modelagem da Gold") a partir de
`datalake/gold/account_monthly_features.parquet`.

Compara 2 modelos lado a lado: `Ridge` (baseline linear regularizado, prova
se um modelo simples já resolve o problema) e `XGBoost` (modelo principal —
captura não linearidade/assimetria nativamente, sem a engenharia de
pré-processamento que o Ridge exige).

Validação: walk-forward (janela expansiva), nunca split aleatório — o
problema é forecasting em painel (várias contas, cada uma com sua série
mensal), e um split de linhas aleatório vazaria meses vizinhos da mesma
conta entre treino e teste. São 4 folds (treino cresce a cada fold, valida
nos 3 meses seguintes) mais 1 holdout final (últimos 3 meses, nunca tocados
até a avaliação).

`target_soma_entradas_proximo_mes` e as colunas monetárias são assimétricas
à direita (ver `notebooks/eda_silver.ipynb`): aplicamos `signed_log1p`
(= sign(x) * log1p(|x|) — generaliza `log1p` para negativos, necessário
para `saldo_fim_mes`) antes de treinar e revertemos antes de medir — MAE/
RMSE reportados estão sempre na escala original (moeda).

`district_id` não entra como feature (identificador de alta cardinalidade;
sua informação socioeconômica já está denormalizada nas colunas numéricas).

MLflow versiona os modelos: 1 run pai (`train_model`) com runs filhas
aninhadas por fold e uma `holdout_final`, onde os 2 modelos finais são
logados e **registrados** no Model Registry (`inflow-forecast-ridge`,
`inflow-forecast-xgboost`) — cada execução cria uma nova versão, histórico
nunca sobrescrito. Tracking store local (SQLite, sem servidor):
`datalake/gold/models/mlflow.db`; artefatos em `datalake/gold/models/mlruns/`.
Para explorar: `mlflow ui --backend-store-uri sqlite:///datalake/gold/models/mlflow.db`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import mlflow
import mlflow.sklearn
import mlflow.xgboost
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

from _common import DATALAKE_DIR, configure_logging, run_cli

logger = configure_logging("train_model")

GOLD_DIR = DATALAKE_DIR / "gold"
GOLD_TABLE = GOLD_DIR / "account_monthly_features.parquet"
MODELS_DIR = GOLD_DIR / "models"

MLFLOW_EXPERIMENT_NAME = "inflow-forecast"
RIDGE_REGISTERED_NAME = "inflow-forecast-ridge"
XGBOOST_REGISTERED_NAME = "inflow-forecast-xgboost"

TARGET_COL = "target_soma_entradas_proximo_mes"
RANDOM_STATE = 42

# Colunas monetárias: assimétricas à direita, recebem signed_log1p.
MONETARY_COLS = [
    "soma_orders_mensais", "loan_payments", "soma_entradas_mes_atual", "soma_saidas_mes_atual",
    "saldo_fim_mes", "media_entradas_ultimos_3_meses", "desvio_padrao_entradas_ultimos_3_meses",
    "media_saidas_ultimos_3_meses",
]
# Demais numéricas: sem transformação de escala logarítmica.
PLAIN_NUMERIC_COLS = [
    "average_salary", "unemployment_rate_1995", "unemployment_rate_1996", "population",
    "entrepreneurs_per_1000", "crimes_1995", "crimes_1996", "urban_population_ratio",
    "titular_age_years", "account_age_months", "n_transacoes_mes",
]
# Booleanas (já 0/1 por natureza) e categóricas de baixa cardinalidade.
BOOLEAN_COLS = ["has_dependente", "loan_ativo_no_mes", "card_ativo_no_mes"]
CATEGORICAL_COLS = ["frequency", "titular_gender"]
# Codificação ordinal fixa para o XGBoost (não dtype "category" nativo do
# pandas): "category" não sobrevive ao round-trip JSON que o MLflow usa
# para validar/servir o modelo (vira "object" e quebra a predição). Com só
# 2-3 níveis por coluna, um código inteiro simples não perde poder
# preditivo relevante frente ao split nativo por categoria.
FREQUENCY_CODES = {"MENSAL": 0, "SEMANAL": 1, "POR TRANSACAO": 2}
GENDER_CODES = {"M": 0, "F": 1}
CATEGORICAL_CODE_MAPS = {"frequency": FREQUENCY_CODES, "titular_gender": GENDER_CODES}

# Validação walk-forward.
N_HOLDOUT_MONTHS = 3
N_WALKFORWARD_FOLDS = 4
VAL_MONTHS_PER_FOLD = 3

XGB_PARAMS = dict(
    n_estimators=500, max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
    min_child_weight=5, tree_method="hist", random_state=RANDOM_STATE,
    early_stopping_rounds=30, eval_metric="mae",
)


# 1) Leitura e preparação da Gold
def load_gold_table(gold_table: Path) -> pd.DataFrame:
    """Lê `account_monthly_features.parquet` e adiciona a codificação cíclica do mês.

    `mes_sin`/`mes_cos` são usadas só pelo Ridge — um modelo linear trataria
    `mes_do_ano` cru como se dezembro estivesse "longe" de janeiro; a
    codificação cíclica corrige isso (o XGBoost usa `mes_do_ano` cru, pois
    árvores não sofrem desse problema).

    Raises:
        FileNotFoundError: se a tabela não existir.
    """
    if not gold_table.is_file():
        raise FileNotFoundError(f"Tabela Gold não encontrada: {gold_table}. Execute gold_features.py antes.")

    df = pd.read_parquet(gold_table)
    df["mes_sin"] = np.sin(2 * np.pi * df["mes_do_ano"] / 12)
    df["mes_cos"] = np.cos(2 * np.pi * df["mes_do_ano"] / 12)
    logger.info("Gold carregada: %s (%d contas distintas, %d meses distintos)", df.shape, df["account_id"].nunique(), df["ano_mes"].nunique())
    return df


# 2) Transformação signed_log1p (target + features monetárias)
def signed_log1p(x: np.ndarray) -> np.ndarray:
    """log1p que aceita valores negativos: sign(x) * log1p(|x|).

    Generalização necessária porque `saldo_fim_mes` pode ser negativo
    (conta no cheque especial); para as demais colunas monetárias
    (sempre >= 0), o comportamento é idêntico a `log1p` puro.
    """
    return np.sign(x) * np.log1p(np.abs(x))


def inverse_signed_log1p(x: np.ndarray) -> np.ndarray:
    """Inversa de `signed_log1p`: sign(x) * expm1(|x|)."""
    return np.sign(x) * np.expm1(np.abs(x))


# 3) Folds walk-forward (janela expansiva) + holdout final
def build_walk_forward_folds(
    months: list[pd.Timestamp],
    n_holdout_months: int = N_HOLDOUT_MONTHS,
    n_folds: int = N_WALKFORWARD_FOLDS,
    val_months_per_fold: int = VAL_MONTHS_PER_FOLD,
) -> tuple[list[tuple[list[pd.Timestamp], list[pd.Timestamp]]], list[pd.Timestamp], list[pd.Timestamp]]:
    """Monta os folds de validação walk-forward e o holdout final.

    Reserva os últimos `n_holdout_months` meses como holdout. Do restante
    ("pool" de CV), reserva os últimos `n_folds * val_months_per_fold` meses
    como a região de "caminhada": em cada fold, o treino é tudo antes do
    início da janela de validação daquele fold (cresce a cada fold), e a
    validação são os `val_months_per_fold` meses daquele bloco.

    Não usamos `sklearn.model_selection.TimeSeriesSplit`: ele particiona por
    número de *linhas*, não por mês de calendário — em um painel com vários
    meses por conta, um corte no meio do mês misturaria contas do mesmo mês
    entre treino e validação, reabrindo o vazamento que o walk-forward
    existe para evitar.

    Returns:
        Tupla (lista de folds [(meses_treino, meses_validação), ...],
        meses de treino do holdout final, meses do holdout final).

    Raises:
        ValueError: se não houver meses suficientes para montar os folds.
    """
    n_walk_months = n_folds * val_months_per_fold
    min_required = n_holdout_months + n_walk_months + 1
    if len(months) < min_required:
        raise ValueError(
            f"Meses insuficientes para montar os folds: {len(months)} disponíveis, "
            f"{min_required} necessários (holdout={n_holdout_months} + walk-forward={n_walk_months} + >=1 de treino inicial)."
        )

    holdout_start_idx = len(months) - n_holdout_months
    holdout_train_months = months[:holdout_start_idx]
    holdout_val_months = months[holdout_start_idx:]

    walk_start_idx = holdout_start_idx - n_walk_months
    folds = []
    for i in range(n_folds):
        val_start = walk_start_idx + i * val_months_per_fold
        val_end = val_start + val_months_per_fold
        folds.append((months[:val_start], months[val_start:val_end]))

    logger.info(
        "Folds walk-forward montados: %d folds (%d meses de validação cada), holdout final com %d meses.",
        n_folds, val_months_per_fold, n_holdout_months,
    )
    return folds, holdout_train_months, holdout_val_months


# 4) Construção dos 2 modelos (Ridge com pré-processamento, XGBoost nativo)
def build_ridge_pipeline() -> Pipeline:
    """Monta o pipeline do Ridge: imputação + signed_log1p + escala + one-hot."""
    monetary_transform = Pipeline([
        ("impute", SimpleImputer(strategy="constant", fill_value=0.0)),
        ("log", FunctionTransformer(signed_log1p, inverse_func=inverse_signed_log1p, feature_names_out="one-to-one")),
        ("scale", StandardScaler()),
    ])
    numeric_transform = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical_transform = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])

    preprocessor = ColumnTransformer([
        ("monetary", monetary_transform, MONETARY_COLS),
        ("numeric", numeric_transform, PLAIN_NUMERIC_COLS + BOOLEAN_COLS + ["mes_sin", "mes_cos"]),
        ("categorical", categorical_transform, CATEGORICAL_COLS),
    ])
    return Pipeline([("prep", preprocessor), ("model", Ridge(alpha=1.0, random_state=RANDOM_STATE))])


def prepare_xgb_features(df: pd.DataFrame) -> pd.DataFrame:
    """Seleciona e tipa as colunas para o XGBoost (categóricas como código inteiro, NaN preservado).

    Tudo em `float64` (não `int`): colunas inteiras não representam `NaN`
    em Python/MLflow — mesmo as que hoje não têm nulo ficam blindadas caso
    a Gold mude no futuro, sem diferença de comportamento para o XGBoost.
    """
    cols = MONETARY_COLS + PLAIN_NUMERIC_COLS + BOOLEAN_COLS + CATEGORICAL_COLS + ["mes_do_ano"]
    X = df[cols].copy()
    for col, code_map in CATEGORICAL_CODE_MAPS.items():
        X[col] = X[col].map(code_map)
    return X.astype("float64")


# 5) Avaliação
def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Calcula MAE, RMSE e R² (sempre na escala original, não em log)."""
    return {
        "MAE": mean_absolute_error(y_true, y_pred),
        "RMSE": root_mean_squared_error(y_true, y_pred),
        "R2": r2_score(y_true, y_pred),
    }


def fit_and_evaluate_fold(train_df: pd.DataFrame, val_df: pd.DataFrame, fold_label: str) -> dict[str, dict[str, float]]:
    """Treina Ridge e XGBoost num fold e avalia na validação daquele fold.

    Returns:
        Dicionário {"ridge": {métricas}, "xgboost": {métricas}}.
    """
    y_train = signed_log1p(train_df[TARGET_COL].to_numpy())
    y_val_true = val_df[TARGET_COL].to_numpy()

    ridge = build_ridge_pipeline()
    ridge.fit(train_df, y_train)
    ridge_pred = inverse_signed_log1p(ridge.predict(val_df))
    ridge_metrics = evaluate(y_val_true, ridge_pred)

    X_train_xgb = prepare_xgb_features(train_df)
    X_val_xgb = prepare_xgb_features(val_df)
    xgb = XGBRegressor(**XGB_PARAMS)
    xgb.fit(X_train_xgb, y_train, eval_set=[(X_val_xgb, signed_log1p(y_val_true))], verbose=False)
    xgb_pred = inverse_signed_log1p(xgb.predict(X_val_xgb))
    xgb_metrics = evaluate(y_val_true, xgb_pred)

    logger.info(
        "  [%s] treino=%d linhas | val=%d linhas | Ridge MAE=%.1f RMSE=%.1f R2=%.3f | XGBoost MAE=%.1f RMSE=%.1f R2=%.3f",
        fold_label, len(train_df), len(val_df),
        ridge_metrics["MAE"], ridge_metrics["RMSE"], ridge_metrics["R2"],
        xgb_metrics["MAE"], xgb_metrics["RMSE"], xgb_metrics["R2"],
    )
    return {"ridge": ridge_metrics, "xgboost": xgb_metrics}


# 6) Configuração do MLflow (tracking store local + artefatos)
def configure_mlflow(models_dir: Path) -> None:
    """Aponta o MLflow para um tracking store local, sob `models_dir`.

    MLflow >= 3 exige um backend de banco de dados para o Model Registry
    (descontinuou o backend de arquivo puro). Usamos SQLite local
    (`models_dir/mlflow.db`): dá o Registry completo sem subir um servidor.
    """
    tracking_uri = f"sqlite:///{(models_dir / 'mlflow.db').resolve()}"
    mlflow.set_tracking_uri(tracking_uri)

    artifact_location = (models_dir / "mlruns").resolve().as_uri()
    if mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT_NAME) is None:
        mlflow.create_experiment(MLFLOW_EXPERIMENT_NAME, artifact_location=artifact_location)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    logger.info("MLflow configurado: tracking_uri=%s | experiment=%s", tracking_uri, MLFLOW_EXPERIMENT_NAME)


def _float64_example(df: pd.DataFrame) -> pd.DataFrame:
    """Converte colunas inteiras para `float64` num exemplo de entrada (só para o `input_example` logado no MLflow).

    Colunas inteiras não representam `NaN` em Python, o que deixa a
    inferência de schema do MLflow frágil a valores ausentes futuros —
    mesmo ajuste já feito em `prepare_xgb_features`.
    """
    df = df.copy()
    int_cols = df.select_dtypes(include=["int64", "Int64"]).columns
    df[int_cols] = df[int_cols].astype("float64")
    return df


def _version_description(metrics: dict[str, float], holdout_val_months: list[pd.Timestamp]) -> str:
    """Descrição curta gravada na versão do modelo registrado (visível no Model Registry)."""
    return (
        f"Holdout {holdout_val_months[0].date()} a {holdout_val_months[-1].date()} | "
        f"MAE={metrics['MAE']:.1f} RMSE={metrics['RMSE']:.1f} R2={metrics['R2']:.3f}"
    )


def run(gold_table: Path = GOLD_TABLE, models_dir: Path = MODELS_DIR) -> None:
    """Executa o pipeline completo: walk-forward CV, holdout final, registro no MLflow.

    Estrutura das runs: 1 run pai (`train_model`, params gerais + resumo
    agregado do walk-forward) com filhas aninhadas — `fold_1`..`fold_N` e
    `holdout_final` (onde os modelos finais são treinados, avaliados e
    **registrados** no Model Registry).
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    configure_mlflow(models_dir)

    df = load_gold_table(gold_table)
    months = sorted(df["ano_mes"].unique())
    folds, holdout_train_months, holdout_val_months = build_walk_forward_folds(months)

    with mlflow.start_run(run_name="train_model") as parent_run:
        mlflow.log_params({
            "target_col": TARGET_COL,
            "n_holdout_months": N_HOLDOUT_MONTHS,
            "n_walkforward_folds": N_WALKFORWARD_FOLDS,
            "val_months_per_fold": VAL_MONTHS_PER_FOLD,
            "ridge_alpha": 1.0,
            **{f"xgb_{k}": v for k, v in XGB_PARAMS.items()},
        })
        mlflow.log_metric("gold_table_rows", len(df))

        logger.info("Iniciando validação walk-forward (%d folds)...", len(folds))
        fold_results = []
        for i, (train_months, val_months) in enumerate(folds):
            train_df = df[df["ano_mes"].isin(train_months)]
            val_df = df[df["ano_mes"].isin(val_months)]
            with mlflow.start_run(run_name=f"fold_{i + 1}", nested=True):
                mlflow.log_params({
                    "n_train_rows": len(train_df),
                    "n_val_rows": len(val_df),
                    "train_start": str(train_months[0].date()),
                    "train_end": str(train_months[-1].date()),
                    "val_start": str(val_months[0].date()),
                    "val_end": str(val_months[-1].date()),
                })
                metrics = fit_and_evaluate_fold(train_df, val_df, f"fold {i + 1}/{len(folds)}")
                for model_name, model_metrics in metrics.items():
                    mlflow.log_metrics({f"{model_name}_{k}": v for k, v in model_metrics.items()})
            fold_results.append(metrics)

        cv_summary = pd.DataFrame([
            {"model": model, "metric": metric, "value": fold[model][metric]}
            for fold in fold_results for model in ("ridge", "xgboost") for metric in ("MAE", "RMSE", "R2")
        ]).groupby(["model", "metric"])["value"].agg(["mean", "std"]).round(3)
        logger.info("Resumo da validação walk-forward (média +/- desvio-padrão entre os %d folds):\n%s", len(folds), cv_summary)

        cv_summary_flat = cv_summary.reset_index()
        for row in cv_summary_flat.itertuples():
            mlflow.log_metric(f"cv_{row.model}_{row.metric}_mean", row.mean)
            mlflow.log_metric(f"cv_{row.model}_{row.metric}_std", row.std)

        cv_metrics_path = models_dir / "cv_metrics_walk_forward.csv"
        cv_summary_flat.to_csv(cv_metrics_path, index=False)
        mlflow.log_artifact(str(cv_metrics_path))

        # Holdout final: treina os modelos "de verdade" e registra no Model Registry.
        logger.info("Treinando os modelos finais (todo o pool de CV) e avaliando no holdout...")
        holdout_train_df = df[df["ano_mes"].isin(holdout_train_months)]
        holdout_val_df = df[df["ano_mes"].isin(holdout_val_months)]

        y_holdout_train = signed_log1p(holdout_train_df[TARGET_COL].to_numpy())
        y_holdout_true = holdout_val_df[TARGET_COL].to_numpy()

        with mlflow.start_run(run_name="holdout_final", nested=True):
            mlflow.log_params({
                "n_train_rows": len(holdout_train_df),
                "n_val_rows": len(holdout_val_df),
                "holdout_start": str(holdout_val_months[0].date()),
                "holdout_end": str(holdout_val_months[-1].date()),
            })

            ridge_final = build_ridge_pipeline()
            ridge_final.fit(holdout_train_df, y_holdout_train)
            ridge_holdout_pred = inverse_signed_log1p(ridge_final.predict(holdout_val_df))
            ridge_holdout_metrics = evaluate(y_holdout_true, ridge_holdout_pred)

            X_holdout_train_xgb = prepare_xgb_features(holdout_train_df)
            X_holdout_val_xgb = prepare_xgb_features(holdout_val_df)
            xgb_final = XGBRegressor(**XGB_PARAMS)
            xgb_final.fit(
                X_holdout_train_xgb, y_holdout_train,
                eval_set=[(X_holdout_val_xgb, signed_log1p(y_holdout_true))], verbose=False,
            )
            xgb_holdout_pred = inverse_signed_log1p(xgb_final.predict(X_holdout_val_xgb))
            xgb_holdout_metrics = evaluate(y_holdout_true, xgb_holdout_pred)

            logger.info(
                "Holdout final (últimos %d meses, %s a %s) | Ridge MAE=%.1f RMSE=%.1f R2=%.3f | XGBoost MAE=%.1f RMSE=%.1f R2=%.3f",
                N_HOLDOUT_MONTHS, holdout_val_months[0].date(), holdout_val_months[-1].date(),
                ridge_holdout_metrics["MAE"], ridge_holdout_metrics["RMSE"], ridge_holdout_metrics["R2"],
                xgb_holdout_metrics["MAE"], xgb_holdout_metrics["RMSE"], xgb_holdout_metrics["R2"],
            )
            mlflow.log_metrics({f"ridge_{k}": v for k, v in ridge_holdout_metrics.items()})
            mlflow.log_metrics({f"xgboost_{k}": v for k, v in xgb_holdout_metrics.items()})

            holdout_metrics_path = models_dir / "holdout_metrics.csv"
            pd.DataFrame([
                {"model": "ridge", **ridge_holdout_metrics},
                {"model": "xgboost", **xgb_holdout_metrics},
            ]).to_csv(holdout_metrics_path, index=False)
            mlflow.log_artifact(str(holdout_metrics_path))

            importances = pd.Series(xgb_final.feature_importances_, index=X_holdout_train_xgb.columns).sort_values(ascending=False)
            importances_path = models_dir / "xgboost_feature_importances.csv"
            importances.to_csv(importances_path, header=["importance"])
            mlflow.log_artifact(str(importances_path))
            logger.info("Top 10 features (XGBoost, importância nativa):\n%s", importances.head(10))

            # Logar + registrar: só os modelos finais (treinados em todo o pool
            # de CV) viram versões no Model Registry — os modelos de cada fold
            # walk-forward são só para validação, não persistidos.
            ridge_info = mlflow.sklearn.log_model(
                ridge_final, name="ridge_model",
                registered_model_name=RIDGE_REGISTERED_NAME,
                input_example=_float64_example(holdout_train_df.drop(columns=[TARGET_COL]).head(5)),
                # skops (padrão do mlflow>=3) audita e recusa desserializar
                # funções customizadas (signed_log1p/inverse_signed_log1p, no
                # pipeline do Ridge) por segurança. É código nosso, de
                # confiança — cloudpickle serializa closures/funções
                # arbitrárias sem essa fricção.
                serialization_format="cloudpickle",
            )
            xgb_info = mlflow.xgboost.log_model(
                xgb_final, name="xgboost_model",
                registered_model_name=XGBOOST_REGISTERED_NAME,
                input_example=X_holdout_train_xgb.head(5),
            )

            client = mlflow.MlflowClient()
            if ridge_info.registered_model_version is not None:
                client.update_model_version(
                    name=RIDGE_REGISTERED_NAME, version=ridge_info.registered_model_version,
                    description=_version_description(ridge_holdout_metrics, holdout_val_months),
                )
            if xgb_info.registered_model_version is not None:
                client.update_model_version(
                    name=XGBOOST_REGISTERED_NAME, version=xgb_info.registered_model_version,
                    description=_version_description(xgb_holdout_metrics, holdout_val_months),
                )

            logger.info(
                "Modelos registrados no MLflow Model Registry: %s v%s | %s v%s",
                RIDGE_REGISTERED_NAME, ridge_info.registered_model_version,
                XGBOOST_REGISTERED_NAME, xgb_info.registered_model_version,
            )

        logger.info(
            "Pipeline concluído (run pai: %s). Métricas e modelos versionados em: %s",
            parent_run.info.run_id, models_dir,
        )


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(description="Treina e valida (walk-forward + holdout) os modelos Ridge e XGBoost sobre a Gold.")
    parser.add_argument("--gold-table", default=str(GOLD_TABLE), help=f"Padrão: {GOLD_TABLE}.")
    parser.add_argument("--models-dir", default=str(MODELS_DIR), help=f"Padrão: {MODELS_DIR}.")
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    return run_cli(lambda: run(Path(args.gold_table), Path(args.models_dir)), logger)


if __name__ == "__main__":
    sys.exit(main())
