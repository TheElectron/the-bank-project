from pathlib import Path

import pytest

from the_bank_project.config import GlobalConfig, KaggleConfig, PathsConfig
from the_bank_project.ingestion import cli


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    calls: list[str] = []
    cfg = GlobalConfig(paths=PathsConfig(data_dir=tmp_path), kaggle=KaggleConfig(dataset="o/d"))
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "download_to_raw", lambda *a, **k: calls.append("raw"))
    monkeypatch.setattr(cli, "to_bronze", lambda *a, **k: calls.append("bronze"))
    return calls


@pytest.mark.parametrize(
    ("step", "expected"),
    [("raw", ["raw"]), ("bronze", ["bronze"]), ("all", ["raw", "bronze"]), (None, ["raw", "bronze"])],
)
def test_cli_runs_requested_steps(patched: list[str], step: str | None, expected: list[str]):
    assert cli.main([step] if step else []) == 0
    assert patched == expected


def test_cli_returns_1_on_error(patched: list[str], monkeypatch: pytest.MonkeyPatch):
    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("falhou")

    monkeypatch.setattr(cli, "download_to_raw", boom)
    assert cli.main(["raw"]) == 1
