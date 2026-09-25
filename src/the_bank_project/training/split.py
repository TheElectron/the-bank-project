"""Divisão cronológica por mês (treino / validação / teste) com meses de folga entre os conjuntos."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from the_bank_project.config import SplitConfig


@dataclass(frozen=True)
class Split:
    """Máscaras booleanas alinhadas ao dataset e os meses-limite de cada conjunto."""

    train: np.ndarray
    val: np.ndarray
    test: np.ndarray
    windows: dict[str, tuple[pd.Timestamp, pd.Timestamp]]

    def describe(self) -> dict[str, str]:
        """Janelas e tamanhos legíveis (para tags do MLflow)."""
        masks = {"train": self.train, "val": self.val, "test": self.test}
        return {
            f"{k}_window": f"{a.date()}..{b.date()} ({int(masks[k].sum())} linhas)"
            for k, (a, b) in self.windows.items()
        }


def chronological_split(timestamps: pd.Series, cfg: SplitConfig) -> Split:
    """Corta por mês para chegar perto de `train_frac`/`val_frac` das linhas (o resto é teste).

    Os cortes são meses inteiros e há `gap_months` descartados entre um conjunto e o seguinte:
    o label de uma linha em T é o outflow de T+1, então sem folga o último mês de treino
    usaria como label um valor que já é feature do primeiro mês de validação.

    Raises:
        ValueError: se algum conjunto ficar vazio.
    """
    counts = timestamps.value_counts().sort_index()
    months = counts.index
    cum = counts.cumsum().to_numpy() / counts.sum()
    train_end = int(np.searchsorted(cum, cfg.train_frac, side="right")) - 1
    val_start = train_end + 1 + cfg.gap_months
    val_end = int(np.searchsorted(cum, cfg.train_frac + cfg.val_frac, side="right")) - 1
    test_start = val_end + 1 + cfg.gap_months
    if train_end < 0 or val_end < val_start or test_start > len(months) - 1:
        raise ValueError("Poucos meses para dividir em treino, validação e teste com essa folga.")
    ranges = {"train": (0, train_end), "val": (val_start, val_end), "test": (test_start, len(months) - 1)}
    masks = {k: ((timestamps >= months[a]) & (timestamps <= months[b])).to_numpy() for k, (a, b) in ranges.items()}
    windows = {k: (months[a], months[b]) for k, (a, b) in ranges.items()}
    return Split(masks["train"], masks["val"], masks["test"], windows)
