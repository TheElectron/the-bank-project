from pathlib import Path

import pytest
from pydantic import ValidationError

from the_bank_project.config import PROJECT_ROOT, load_config


def test_load_default_config():
    cfg = load_config()
    assert cfg.kaggle.dataset == "marceloventura/the-berka-dataset"
    assert cfg.paths.raw == PROJECT_ROOT / "data" / "raw"
    assert cfg.paths.gold == PROJECT_ROOT / "data" / "gold"


def test_absolute_data_dir_is_kept(tmp_path: Path):
    yaml_file = tmp_path / "c.yaml"
    yaml_file.write_text(f"paths:\n  data_dir: {tmp_path}\nkaggle:\n  dataset: a/b\n")
    cfg = load_config(yaml_file)
    assert cfg.paths.silver == tmp_path / "silver"


def test_invalid_config_raises(tmp_path: Path):
    yaml_file = tmp_path / "c.yaml"
    yaml_file.write_text("paths: {}\n")  # falta `kaggle`
    with pytest.raises(ValidationError):
        load_config(yaml_file)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nao_existe.yaml")
