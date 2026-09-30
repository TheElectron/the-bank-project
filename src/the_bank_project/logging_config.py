"""Configuração de logging a partir do arquivo `configs/logger.yaml`."""


import yaml
import logging
import logging.config
from pathlib import Path

from the_bank_project.config import CONFIGS_DIR


def configure_logging(path: Path = CONFIGS_DIR / "logger.yaml") -> None:
    """
        Método responsável pela configuração de logging .
    """
    with path.open(encoding="utf-8") as f:
        logging.config.dictConfig(yaml.safe_load(f))
