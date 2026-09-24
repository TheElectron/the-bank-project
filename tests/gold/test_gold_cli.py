from pathlib import Path

import pytest

from the_bank_project.config import GlobalConfig, KaggleConfig, PathsConfig
from the_bank_project.gold import cli


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[tuple[Path, Path]]:
    calls: list[tuple[Path, Path]] = []
    cfg = GlobalConfig(paths=PathsConfig(data_dir=tmp_path), kaggle=KaggleConfig(dataset="o/d"))
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "silver_to_gold", lambda s, g: calls.append((s, g)))
    return calls


def test_cli_runs_silver_to_gold_with_configured_paths(calls: list[tuple[Path, Path]], tmp_path: Path):
    assert cli.main([]) == 0
    assert calls == [(tmp_path / "silver", tmp_path / "gold")]


def test_cli_returns_1_on_error(calls: list[tuple[Path, Path]], monkeypatch: pytest.MonkeyPatch):
    def boom(*a: object) -> None:
        raise RuntimeError("falhou")

    monkeypatch.setattr(cli, "silver_to_gold", boom)
    assert cli.main([]) == 1
