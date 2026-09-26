"""CLI do monitoramento: `python -m the_bank_project.monitoring [drift|push]`."""

import argparse
import logging
import sys
from collections.abc import Sequence

from the_bank_project.config import Settings, load_config
from the_bank_project.logging_config import configure_logging
from the_bank_project.monitoring.drift import load_summary, run_drift
from the_bank_project.monitoring.metrics import push_drift

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Executa a etapa pedida. Drift detectado é resultado, não erro: só falha se a etapa quebrar."""
    parser = argparse.ArgumentParser(prog="the_bank_project.monitoring", description="Monitoramento de drift.")
    parser.add_argument(
        "step", choices=["drift", "push"], nargs="?", default="drift",
        help="drift: calcula o relatório (e publica, se houver PUSHGATEWAY_URL); push: só publica o último resumo.",
    )  # fmt: skip
    args = parser.parse_args(argv)
    configure_logging()
    url = Settings().pushgateway_url
    try:
        cfg = load_config()
        summary = run_drift(cfg) if args.step == "drift" else load_summary(cfg.paths.monitoring)
        if url:
            push_drift(summary, url)
        elif args.step == "push":
            raise ValueError("Defina PUSHGATEWAY_URL (ex.: http://localhost:9091) para publicar o resumo.")
    except Exception:
        logger.exception("Etapa '%s' interrompida por erro.", args.step)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
