"""Ingestão: Kaggle → Raw (.csv originais) → Bronze (.parquet, cópia 1:1)."""

from the_bank_project.ingestion.bronze import csv_to_parquet, to_bronze
from the_bank_project.ingestion.raw import download_dataset, download_to_raw, extract_csvs

__all__ = ["csv_to_parquet", "download_dataset", "download_to_raw", "extract_csvs", "to_bronze"]
