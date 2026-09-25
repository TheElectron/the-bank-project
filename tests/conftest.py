import shutil
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest
from mlflow import MlflowClient

from the_bank_project.config import PROJECT_ROOT, GlobalConfig, KaggleConfig, PathsConfig, SplitConfig, TrainingConfig
from the_bank_project.gold import build_gold

D = pd.Timestamp


def _trans(rows: list[tuple]) -> pd.DataFrame:
    cols = ["trans_id", "account_id", "date", "type", "operation", "amount", "balance", "k_symbol"]
    df = pd.DataFrame(rows, columns=cols).astype({"trans_id": "string", "account_id": "string"})
    df[["type", "operation", "k_symbol"]] = df[["type", "operation", "k_symbol"]].astype("string")
    df[["amount", "balance"]] = df[["amount", "balance"]].astype("Float64")
    return df.assign(bank=pd.NA, account=pd.NA)


@pytest.fixture
def silver() -> dict[str, pd.DataFrame]:
    """Silver sintética: conta 1 com mês de lacuna (fev/93) e dia com `trans_id` fora de ordem; conta 2 curta."""
    district = pd.DataFrame({
        "district_id": ["1", "2"], "district_name": ["Praha", "Brno"], "region": ["Prague", "south Moravia"],
        "population": [1000, 500], "urban_population_ratio": [100.0, 50.0], "average_salary": [12000, 9000],
        "unemployment_rate_1995": [0.3, pd.NA], "unemployment_rate_1996": [0.4, 2.0],
        "entrepreneurs_per_1000": [167, 100], "crimes_1995": [10, pd.NA], "crimes_1996": [20, 30],
    }).astype({"district_id": "string", "unemployment_rate_1995": "Float64", "crimes_1995": "Int64"})  # fmt: skip
    account = pd.DataFrame({
        "account_id": ["1", "2"], "district_id": ["1", "2"], "frequency": ["MENSAL", "SEMANAL"],
        "date": [D("1993-01-01"), D("1993-02-01")], "loan_id": ["7", pd.NA], "loan_date": [D("1993-06-01"), pd.NaT],
        "loan_amount": [12000.0, pd.NA], "loan_duration": [12, pd.NA], "loan_payments": [1000.0, pd.NA],
        "loan_status": ["C", pd.NA],
    }).astype({"account_id": "string", "district_id": "string", "loan_amount": "Float64", "loan_duration": "Int64",
               "loan_payments": "Float64"})  # fmt: skip
    client = pd.DataFrame({
        "client_id": ["10", "11", "12"], "account_id": ["1", "1", "2"],
        "relationship_type": ["TITULAR", "DEPENDENTE", "TITULAR"], "district_id": ["2", "1", "2"],
        "gender": ["F", "M", "M"], "birth_date": [D("1970-12-13"), D("1990-01-01"), D("1945-02-04")],
        "card_id": ["9", pd.NA, pd.NA], "card_type": ["gold", pd.NA, pd.NA],
        "card_issued": [D("1993-11-07"), pd.NaT, pd.NaT],
    }).astype({"client_id": "string", "account_id": "string", "district_id": "string"})  # fmt: skip
    trans = _trans([
        ("1", "1", D("1993-01-05"), "CREDITO", "DEPOSITO_DINHEIRO", 1000.0, 1000.0, None),
        ("2", "1", D("1993-01-20"), "SAQUE", "SAQUE_DINHEIRO", 300.0, 700.0, None),
        # mesmo dia, ordem real: 6 (700 -> 500) e depois 5 (500 -> 1200): o `trans_id` engana
        ("6", "1", D("1993-03-10"), "DEBITO", "TRANSFERENCIA_ENVIADA", 200.0, 500.0, "PAGAMENTO_EMPRESTIMO"),
        ("5", "1", D("1993-03-10"), "CREDITO", "TRANSFERENCIA_RECEBIDA", 700.0, 1200.0, None),
        ("8", "2", D("1993-02-03"), "CREDITO", "DEPOSITO_DINHEIRO", 50.0, 50.0, None),
    ])  # fmt: skip
    return {"account": account, "client": client, "district": district, "trans": trans}


@pytest.fixture
def repo(silver: dict[str, pd.DataFrame], tmp_path: Path) -> Path:
    """Cópia do repositório Feast sobre uma Gold sintética, no mesmo layout (`../data/gold`)."""
    gold_dir = tmp_path / "data" / "gold"
    gold_dir.mkdir(parents=True)
    for name, df in build_gold(silver).items():
        df.to_parquet(gold_dir / f"{name}.parquet", index=False)
    repo = tmp_path / "feature_repo"
    repo.mkdir()
    for name in ("feature_store.yaml", "features.py"):
        shutil.copy(PROJECT_ROOT / "feature_repo" / name, repo / name)
    return repo


@pytest.fixture(scope="session")
def db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """SQLite do MLflow já migrado. Criar o schema custa ~45 s; copiar o arquivo, milissegundos."""
    path = tmp_path_factory.mktemp("mlflow_template") / "mlflow.db"
    MlflowClient(tracking_uri=f"sqlite:///{path}").search_experiments()
    return path


@pytest.fixture(scope="session")
def cfg_factory(db_template: Path) -> Callable[[Path], GlobalConfig]:
    """Config isolada: dados e MLflow (banco copiado do template) em `root`, poucos trials."""

    def make(root: Path) -> GlobalConfig:
        shutil.copy(db_template, root / "mlflow.db")
        training = TrainingConfig(
            n_tuning_trials=1, split=SplitConfig(train_frac=0.6, val_frac=0.2, gap_months=1),
            tracking_uri=f"sqlite:///{root / 'mlflow.db'}",
        )  # fmt: skip
        return GlobalConfig(paths=PathsConfig(data_dir=root), kaggle=KaggleConfig(dataset="o/d"), training=training)

    return make


@pytest.fixture
def cfg(tmp_path: Path, cfg_factory: Callable[[Path], GlobalConfig]) -> GlobalConfig:
    return cfg_factory(tmp_path)


@pytest.fixture(autouse=True)
def _no_ambient_mlflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
