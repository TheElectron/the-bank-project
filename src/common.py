"""Utilitários compartilhados entre os módulos de `src/` (ver CONTRIBUTING.md)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATALAKE_DIR = PROJECT_ROOT / "datalake"
CONFIGS_DIR = PROJECT_ROOT / "configs"

load_dotenv(PROJECT_ROOT / ".env")


def configure_logging(name: str) -> logging.Logger:
    """Configura o logging padrão do projeto (nível INFO) e retorna o logger nomeado."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(name)


def run_cli(fn: Callable[[], None], logger: logging.Logger) -> int:
    """Executa `fn`, convertendo uma exceção em código de saída 1 (para `main()`)."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - captura ampla e intencional: nível mais alto do processo
        logger.error("Falha na execução do script: %s", exc)
        return 1
    return 0
