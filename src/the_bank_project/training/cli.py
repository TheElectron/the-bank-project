"""CLI do treino: `python -m the_bank_project.training [labels|train|tune|promote]`."""

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
    parser.add_argument("step", choices=["labels", "train", "tune", "promote"], help="Etapa a executar.")
    parser.add_argument(
        "--trials", type=int, default=None,
        help="train: sorteios por modelo (sem best_params.yaml); tune: tentativas do Optuna (config).",
    )  # fmt: skip
    args = parser.parse_args(argv)
    configure_logging()
    cfg = load_config()
    if args.trials is not None:
        cfg.training.n_tuning_trials = cfg.tuning.n_trials = args.trials
    try:
        if args.step == "labels":
            gold_to_labels(cfg.paths.gold)
        elif args.step == "train":
            run_training(cfg)
        elif args.step == "tune":
            from the_bank_project.training.tuning import run_tuning  # grupo `tuning`: fora das imagens de produção

            run_tuning(cfg)
        else:
            promote(cfg)
    except Exception:
        logger.exception("Etapa '%s' interrompida por erro.", args.step)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
