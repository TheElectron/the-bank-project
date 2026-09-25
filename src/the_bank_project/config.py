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


class GlobalConfig(BaseModel):
    """Configuração global, espelho de `configs/global_config.yaml`."""

    paths: PathsConfig = PathsConfig()
    kaggle: KaggleConfig
    feast: FeastConfig = FeastConfig()
    training: TrainingConfig = TrainingConfig()


class Settings(BaseSettings):
    """Variáveis de ambiente / `.env` (segredos e overrides locais)."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    config_path: Path = DEFAULT_CONFIG_PATH
    kaggle_username: str | None = None
    kaggle_key: str | None = None
    kaggle_api_token: str | None = None
    mlflow_tracking_uri: str | None = None


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
