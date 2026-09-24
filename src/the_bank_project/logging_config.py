"""Configuração de logging a partir de `configs/logger.yaml`."""

import logging
import logging.config
from pathlib import Path

import yaml

from the_bank_project.config import CONFIGS_DIR


def configure_logging(path: Path = CONFIGS_DIR / "logger.yaml") -> None:
    """Aplica a configuração de logging (`dictConfig`) do YAML."""
    with path.open(encoding="utf-8") as f:
        logging.config.dictConfig(yaml.safe_load(f))
