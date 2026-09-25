from pathlib import Path

import pandas as pd
import pytest

from the_bank_project.training.labels import LABELS_TABLE, MONTHLY_TABLE, TARGET, build_labels, gold_to_labels


def _monthly(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["account_id", "reference_month", "outflow_amount"])
    return df.assign(reference_month=pd.to_datetime(df["reference_month"]))


def test_label_is_next_month_outflow_and_last_month_is_dropped():
    monthly = _monthly([("1", "1995-01-31", 10.0), ("1", "1995-02-28", 20.0), ("1", "1995-03-31", 30.0),
                        ("2", "1995-02-28", 5.0), ("2", "1995-03-31", 7.0)])  # fmt: skip
    labels = build_labels(monthly).set_index(["account_id", "event_timestamp"])[TARGET]
    assert labels.to_dict() == {
        ("1", pd.Timestamp("1995-01-31")): 20.0, ("1", pd.Timestamp("1995-02-28")): 30.0,
        ("2", pd.Timestamp("1995-02-28")): 7.0,
    }  # fmt: skip


def test_labels_do_not_cross_accounts():
    monthly = _monthly([("1", "1995-01-31", 10.0), ("2", "1995-02-28", 99.0)])
    assert build_labels(monthly).empty  # cada conta tem 1 mês só: nenhum T+1


def test_non_contiguous_months_are_rejected():
    monthly = _monthly([("1", "1995-01-31", 10.0), ("1", "1995-03-31", 30.0)])
    with pytest.raises(ValueError, match="não contígua"):
        build_labels(monthly)


def test_gold_to_labels_writes_parquet_next_to_gold_and_is_idempotent(tmp_path: Path):
    _monthly([("1", "1995-01-31", 10.0), ("1", "1995-02-28", 20.0)]).to_parquet(tmp_path / f"{MONTHLY_TABLE}.parquet")
    first = gold_to_labels(tmp_path)
    assert first == gold_to_labels(tmp_path) == tmp_path / f"{LABELS_TABLE}.parquet"
    assert pd.read_parquet(first)[TARGET].tolist() == [20.0]
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_gold_to_labels_requires_the_gold(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Gold"):
        gold_to_labels(tmp_path)
