"""CLI do treino: `python -m the_bank_project.training [labels|train|promote]`."""

import argparse
import logging
import sys
from collections.abc import Sequence

from the_bank_project.config import load_config
from the_bank_project.logging_config import configure_logging
from the_bank_project.training.labels import gold_to_labels
from the_bank_project.training.registry import promote
from the_bank_project.training.train import run_training

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Executa a etapa pedida. Retorna o código de saída do processo."""
    parser = argparse.ArgumentParser(prog="the_bank_project.training", description="Treino do modelo de gastos.")
    parser.add_argument("step", choices=["labels", "train", "promote"], help="Etapa a executar.")
    parser.add_argument("--trials", type=int, default=None, help="Sorteios de hiperparâmetros por modelo (config).")
    args = parser.parse_args(argv)
    configure_logging()
    cfg = load_config()
    if args.trials is not None:
        cfg.training.n_tuning_trials = args.trials
    try:
        if args.step == "labels":
            gold_to_labels(cfg.paths.gold)
        elif args.step == "train":
            run_training(cfg)
        else:
            promote(cfg)
    except Exception:
        logger.exception("Etapa '%s' interrompida por erro.", args.step)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
