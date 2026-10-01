"""
    Bronze (`.parquet`) → Silver (`.parquet` limpos e tipados) [CLI]
    Este módulo contém a CLI para executar a transformação de dados da camada Bronze para a Silver.
    `python -m the_bank_project.silver`
"""

import argparse
import logging
import sys
from collections.abc import Sequence

from the_bank_project.config import load_config
from the_bank_project.logging_config import configure_logging
from the_bank_project.silver.transform import bronze_to_silver

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """
        Executa Bronze → Silver. 
    """
    argparse.ArgumentParser(prog="the_bank_project.silver", description="[Ingestão] Bronze → Silver").parse_args(argv)
    configure_logging()
    cfg = load_config()
    try:
        bronze_to_silver(cfg.paths.bronze, cfg.paths.silver)
    except Exception:
        logger.exception("Bronze → Silver interrompido por erro.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
