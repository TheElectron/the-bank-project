from pathlib import Path

import pandas as pd
import pytest

from the_bank_project.ingestion.bronze import csv_to_parquet, to_bronze


def write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_csv_to_parquet_is_a_1to1_copy(tmp_path: Path):
    content = '"account_id";"date";"frequency"\n"0001";"930101";""\n"0002";"NA";"POPLATEK MESICNE"\n'
    csv = write_csv(tmp_path / "account.csv", content)
    out = csv_to_parquet(csv, tmp_path / "bronze")
    df = pd.read_parquet(out)
    assert out.name == "account.parquet"
    assert list(df.columns) == ["account_id", "date", "frequency"]
    assert df["account_id"].tolist() == ["0001", "0002"]  # zeros à esquerda preservados
    assert df["frequency"].tolist() == ["", "POPLATEK MESICNE"]  # "" não vira NaN
    assert df["date"].tolist() == ["930101", "NA"]  # "NA" não vira NaN
    assert (df.dtypes == df.dtypes.iloc[0]).all()  # tudo texto, sem inferência


def test_csv_to_parquet_overwrites_and_leaves_no_tmp(tmp_path: Path):
    csv = write_csv(tmp_path / "t.csv", "a;b\n1;2\n")
    bronze = tmp_path / "bronze"
    csv_to_parquet(csv, bronze)
    write_csv(csv, "a;b\n1;2\n3;4\n")
    out = csv_to_parquet(csv, bronze)
    assert len(pd.read_parquet(out)) == 2
    assert [p.name for p in bronze.iterdir()] == ["t.parquet"]


def test_to_bronze_converts_all_csvs(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_csv(raw / "a.csv", "x\n1\n")
    write_csv(raw / "b.csv", "y\n2\n")
    outs = to_bronze(raw, tmp_path / "bronze")
    assert [p.name for p in outs] == ["a.parquet", "b.parquet"]


def test_to_bronze_empty_raw_raises(tmp_path: Path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(FileNotFoundError):
        to_bronze(tmp_path / "raw", tmp_path / "bronze")
