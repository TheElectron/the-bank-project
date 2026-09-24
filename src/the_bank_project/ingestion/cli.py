"""CLI da ingestão: `python -m the_bank_project.ingestion [raw|bronze|all]`."""

import argparse
import logging
import sys
from collections.abc import Sequence

from the_bank_project.config import load_config
from the_bank_project.ingestion.bronze import to_bronze
from the_bank_project.ingestion.raw import download_to_raw
from the_bank_project.logging_config import configure_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Define os argumentos da CLI."""
    parser = argparse.ArgumentParser(prog="the_bank_project.ingestion", description="Ingestão Kaggle → Raw → Bronze.")
    parser.add_argument(
        "step", nargs="?", choices=["raw", "bronze", "all"], default="all", help="Etapa a executar (padrão: all)."
    )
    parser.add_argument("--force", action="store_true", help="Baixa de novo mesmo com a Raw já populada.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Executa a etapa pedida. Retorna o código de saída do processo."""
    args = build_parser().parse_args(argv)
    configure_logging()
    cfg = load_config()
    try:
        if args.step in ("raw", "all"):
            download_to_raw(cfg.kaggle.dataset, cfg.paths.raw, force=args.force)
        if args.step in ("bronze", "all"):
            to_bronze(cfg.paths.raw, cfg.paths.bronze)
    except Exception:
        logger.exception("Ingestão interrompida por erro.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
