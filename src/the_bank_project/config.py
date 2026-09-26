"""Configuração do projeto: YAML validado via Pydantic + variáveis de ambiente (`.env`)."""

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS_DIR = PROJECT_ROOT / "configs"
DEFAULT_CONFIG_PATH = CONFIGS_DIR / "global_config.yaml"


class PathsConfig(BaseModel):
    """Diretórios do data lake Medallion."""

    data_dir: Path = Path("data")

    def _resolve(self, *parts: str) -> Path:
        base = self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir
        return base.joinpath(*parts)

    @property
    def data(self) -> Path:
        return self._resolve()

    @property
    def raw(self) -> Path:
        return self._resolve("raw")

    @property
    def bronze(self) -> Path:
        return self._resolve("bronze")

    @property
    def silver(self) -> Path:
        return self._resolve("silver")

    @property
    def gold(self) -> Path:
        return self._resolve("gold")

    @property
    def monitoring(self) -> Path:
        return self._resolve("monitoring")


class KaggleConfig(BaseModel):
    """Origem dos dados brutos."""

    dataset: str


class FeastConfig(BaseModel):
    """Repositório da feature store (Feast)."""

    repo_path: Path = Path("feature_repo")

    @property
    def repo(self) -> Path:
        return self.repo_path if self.repo_path.is_absolute() else PROJECT_ROOT / self.repo_path


class SplitConfig(BaseModel):
    """Divisão cronológica do dataset de treino, feita por mês (não por linha)."""

    train_frac: float = 0.70
    val_frac: float = 0.20
    gap_months: int = 1  # meses descartados entre os conjuntos, para o label de um não cair no seguinte


class TrainingConfig(BaseModel):
    """Treino, validação e registry do modelo de regressão de gastos."""

    experiment: str = "regressao_outflow"
    registered_model: str = "outflow_regression"
    feature_service: str = "outflow_regression"
    split: SplitConfig = SplitConfig()
    n_tuning_trials: int = 8  # configurações sorteadas por modelo, além da padrão
    log_target: bool = True  # treina em log1p(y) e reverte antes de medir (métricas na escala original)
    seed: int = 42
    tracking_uri: str | None = None  # None: SQLite local em data/mlflow/ (ver `Settings.mlflow_tracking_uri`)


class ServingConfig(BaseModel):
    """API de inferência (FastAPI)."""

    host: str = "0.0.0.0"
    port: int = 8000
    max_batch: int = 100  # contas por chamada a /predict
    model_poll_seconds: int = 60  # 0 desliga: consulta o alias `champion` e recarrega se mudou
    history_months: int = 12  # meses de histórico no detalhe da conta


class MonitoringConfig(BaseModel):
    """Drift de dados (Evidently): referência = meses de treino/validação, atual = últimos meses da Gold."""

    current_months: int = 3  # tamanho da janela "atual" (replay temporal: o dataset é histórico)
    feature_threshold: float = (
        0.1  # uma feature deriva se a distância de Wasserstein (em desvios da referência) passar disso
    )
    drift_share_threshold: float = 0.5  # há drift no dataset se essa fração das features (ou mais) derivar
    retrain_enabled: bool = True  # se False, o drift nunca dispara o re-treino
    retrain_cooldown_days: int = 14  # intervalo mínimo entre re-treinos disparados por drift (evita loops)


class GlobalConfig(BaseModel):
    """Configuração global, espelho de `configs/global_config.yaml`."""

    paths: PathsConfig = PathsConfig()
    kaggle: KaggleConfig
    feast: FeastConfig = FeastConfig()
    training: TrainingConfig = TrainingConfig()
    serving: ServingConfig = ServingConfig()
    monitoring: MonitoringConfig = MonitoringConfig()


class Settings(BaseSettings):
    """Variáveis de ambiente / `.env` (segredos e overrides locais)."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    config_path: Path = DEFAULT_CONFIG_PATH
    kaggle_username: str | None = None
    kaggle_key: str | None = None
    kaggle_api_token: str | None = None
    mlflow_tracking_uri: str | None = None
    pushgateway_url: str | None = None  # Pushgateway do Prometheus; sem ele o resumo de drift não é publicado


def load_config(path: Path | None = None) -> GlobalConfig:
    """Carrega e valida o YAML de configuração.

    Args:
        path: caminho do YAML. Se omitido, usa `CONFIG_PATH` do ambiente ou
            `configs/global_config.yaml`.

    Raises:
        FileNotFoundError: se o arquivo não existir.
        pydantic.ValidationError: se o conteúdo não bater com o schema.
    """
    path = path or Settings().config_path
    with path.open(encoding="utf-8") as f:
        return GlobalConfig.model_validate(yaml.safe_load(f))
