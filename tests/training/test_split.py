import numpy as np
import pandas as pd
import pytest

from the_bank_project.config import SplitConfig
from the_bank_project.training.split import chronological_split


def _timestamps(months: int, per_month: int = 10) -> pd.Series:
    return pd.Series(np.repeat(pd.date_range("1995-01-31", periods=months, freq="ME"), per_month))


def test_split_is_chronological_disjoint_and_leaves_a_gap():
    ts = _timestamps(30)
    s = chronological_split(ts, SplitConfig(train_frac=0.7, val_frac=0.2, gap_months=1))
    assert not (s.train & s.val).any() and not (s.val & s.test).any() and not (s.train & s.test).any()
    assert ts[s.train].max() < ts[s.val].min() and ts[s.val].max() < ts[s.test].min()
    months = ts.drop_duplicates().tolist()
    assert months.index(ts[s.val].min()) - months.index(ts[s.train].max()) == 2  # 1 mês descartado
    assert months.index(ts[s.test].min()) - months.index(ts[s.val].max()) == 2
    assert (s.train | s.val | s.test).sum() == len(ts) - 20  # 2 folgas x 10 linhas


def test_split_cuts_by_row_share_not_by_month_share():
    counts = [100] * 6 + [10] * 12  # linhas densas no começo: 70% das linhas cabem em 5 dos 18 meses
    ts = pd.Series(np.repeat(pd.date_range("1995-01-31", periods=len(counts), freq="ME"), counts))
    s = chronological_split(ts, SplitConfig(train_frac=0.7, val_frac=0.2, gap_months=0))
    assert s.train.mean() == pytest.approx(0.7, abs=0.02)
    assert ts[s.train].nunique() == 5  # por mês seriam ~13 dos 18


def test_split_describe_lists_windows_and_sizes():
    s = chronological_split(_timestamps(30), SplitConfig())
    assert set(s.describe()) == {"train_window", "val_window", "test_window"}
    assert "linhas" in s.describe()["test_window"]


def test_split_with_too_few_months_fails():
    with pytest.raises(ValueError, match="Poucos meses"):
        chronological_split(_timestamps(3), SplitConfig(gap_months=1))
