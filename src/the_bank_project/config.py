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


class GlobalConfig(BaseModel):
    """Configuração global, espelho de `configs/global_config.yaml`."""

    paths: PathsConfig = PathsConfig()
    kaggle: KaggleConfig
    feast: FeastConfig = FeastConfig()


class Settings(BaseSettings):
    """Variáveis de ambiente / `.env` (segredos e overrides locais)."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    config_path: Path = DEFAULT_CONFIG_PATH
    kaggle_username: str | None = None
    kaggle_key: str | None = None
    kaggle_api_token: str | None = None


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
