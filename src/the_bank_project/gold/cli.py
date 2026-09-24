"""CLI da Gold: `python -m the_bank_project.gold`."""

import argparse
import logging
import sys
from collections.abc import Sequence

from the_bank_project.config import load_config
from the_bank_project.gold.transform import silver_to_gold
from the_bank_project.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Executa Silver → Gold. Retorna o código de saída do processo."""
    argparse.ArgumentParser(prog="the_bank_project.gold", description="Silver → Gold.").parse_args(argv)
    configure_logging()
    cfg = load_config()
    try:
        silver_to_gold(cfg.paths.silver, cfg.paths.gold)
    except Exception:
        logger.exception("Silver → Gold interrompido por erro.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
