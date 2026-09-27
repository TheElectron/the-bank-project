"""Dobras de validação cruzada temporal: ordem, folga e uso só dos meses permitidos."""

import numpy as np
import pandas as pd
import pytest

from the_bank_project.training.cv import expanding_folds

MONTHS = pd.date_range("1996-01-31", periods=20, freq="ME")
TS = pd.Series(np.repeat(MONTHS, 3))  # 3 linhas por mês


def months_of(mask: np.ndarray) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted(TS[mask].unique()))


def test_each_fold_trains_on_the_past_and_validates_on_the_next_block_with_a_gap() -> None:
    mask = np.ones(len(TS), dtype=bool)
    folds = expanding_folds(TS, mask, n_folds=3, gap_months=1)
    assert len(folds) == 3
    for train, val in folds:
        assert not (train & val).any()
        assert months_of(train).max() < months_of(val).min()
        gap = (MONTHS.get_loc(months_of(val).min()) - MONTHS.get_loc(months_of(train).max())) - 1
        assert gap == 1  # exatamente 1 mês descartado entre o treino e a validação


def test_train_windows_expand_and_validation_blocks_do_not_overlap() -> None:
    folds = expanding_folds(TS, np.ones(len(TS), dtype=bool), n_folds=3, gap_months=1)
    sizes = [int(t.sum()) for t, _ in folds]
    assert sizes == sorted(sizes) and len(set(sizes)) == 3
    vals = [set(months_of(v)) for _, v in folds]
    assert all(not (a & b) for i, a in enumerate(vals) for b in vals[i + 1 :])


def test_last_fold_absorbs_the_remainder_and_covers_the_last_month() -> None:
    _, val = expanding_folds(TS, np.ones(len(TS), dtype=bool), n_folds=3, gap_months=1)[-1]
    assert months_of(val).max() == MONTHS[-1]


def test_folds_never_touch_rows_outside_the_mask() -> None:
    mask = (MONTHS[13] >= TS).to_numpy()  # ex.: só os meses de treino do split
    for train, val in expanding_folds(TS, mask, n_folds=3, gap_months=1):
        assert not ((train | val) & ~mask).any()


def test_too_few_months_raises() -> None:
    mask = (MONTHS[3] >= TS).to_numpy()
    with pytest.raises(ValueError, match="não bastam"):
        expanding_folds(TS, mask, n_folds=4, gap_months=1)
