"""CLI da feature store: `python -m the_bank_project.features [apply|materialize|all]`."""

import argparse
import logging
import sys
from collections.abc import Sequence

from the_bank_project.features.store import apply_repo, materialize_all
from the_bank_project.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Executa `apply` e/ou `materialize`. Retorna o código de saída do processo."""
    parser = argparse.ArgumentParser(prog="the_bank_project.features", description="Feature store (Feast).")
    parser.add_argument(
        "step", nargs="?", choices=["apply", "materialize", "all"], default="all", help="Etapa (padrão: all)."
    )
    args = parser.parse_args(argv)
    configure_logging()
    try:
        if args.step in ("apply", "all"):
            apply_repo()
        if args.step in ("materialize", "all"):
            materialize_all()
    except Exception:
        logger.exception("Feature store interrompida por erro.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
