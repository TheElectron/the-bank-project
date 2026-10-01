"""
    Este módulo contém funções para realizar validação cruzada (temporal).
"""

import numpy as np
import pandas as pd


def expanding_folds(
    timestamps: pd.Series, mask: np.ndarray, n_folds: int, gap_months: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
        Divide os meses de `mask` em `n_folds + 1` blocos; 
        a dobra k valida no bloco k e treina em tudo antes dele.

    Returns:
        Lista de `(máscara de treino, máscara de validação)`, alinhadas ao dataset, da mais antiga à mais recente.

    Raises:
        ValueError: se houver poucos meses para `n_folds` dobras com essa folga.
    """
    months = np.sort(timestamps[mask].unique())
    block = len(months) // (n_folds + 1)
    if n_folds < 1 or block <= gap_months:
        raise ValueError(f"{len(months)} meses não bastam para {n_folds} dobras com folga de {gap_months}.")
    folds = []
    for k in range(1, n_folds + 1):
        val_end = len(months) if k == n_folds else (k + 1) * block  # a última dobra absorve o resto
        train = mask & (timestamps <= months[k * block - gap_months - 1]).to_numpy()
        val = mask & (timestamps >= months[k * block]).to_numpy() & (timestamps <= months[val_end - 1]).to_numpy()
        folds.append((train, val))
    return folds
