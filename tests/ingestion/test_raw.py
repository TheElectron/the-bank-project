import zipfile
from pathlib import Path

import pytest

from the_bank_project.ingestion import raw


def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_extract_csvs_flattens_and_ignores_non_csv(tmp_path: Path):
    zip_path = make_zip(
        tmp_path / "d.zip",
        {
            "account.csv": b"a;b\n1;2\n",
            "sub/trans.csv": b"x\n1\n",
            "readme.txt": b"hi",
            "__MACOSX/._account.csv": b"junk",
        },
    )
    files = raw.extract_csvs(zip_path, tmp_path / "raw")
    assert [f.name for f in files] == ["account.csv", "trans.csv"]
    assert (tmp_path / "raw" / "account.csv").read_bytes() == b"a;b\n1;2\n"  # bytes intactos
    assert not list((tmp_path / "raw").glob(".*.tmp"))


def test_extract_csvs_blocks_path_traversal(tmp_path: Path):
    zip_path = make_zip(tmp_path / "d.zip", {"../../evil.csv": b"x\n"})
    raw.extract_csvs(zip_path, tmp_path / "raw")
    assert (tmp_path / "raw" / "evil.csv").exists()
    assert not (tmp_path.parent / "evil.csv").exists()


def test_extract_csvs_without_csv_raises(tmp_path: Path):
    zip_path = make_zip(tmp_path / "d.zip", {"a.txt": b"x"})
    with pytest.raises(FileNotFoundError):
        raw.extract_csvs(zip_path, tmp_path / "raw")


@pytest.fixture
def fake_download(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def _download(dataset: str, dest_dir: Path) -> Path:
        calls.append(dataset)
        return make_zip(dest_dir / "d.zip", {"account.csv": b"a\n1\n"})

    monkeypatch.setattr(raw, "download_dataset", _download)
    return calls


def test_download_to_raw_is_idempotent(tmp_path: Path, fake_download: list[str]):
    raw_dir = tmp_path / "raw"
    raw.download_to_raw("o/d", raw_dir)
    raw.download_to_raw("o/d", raw_dir)
    assert fake_download == ["o/d"]  # 2ª chamada não baixa de novo


def test_download_to_raw_force_redownloads(tmp_path: Path, fake_download: list[str]):
    raw_dir = tmp_path / "raw"
    raw.download_to_raw("o/d", raw_dir)
    raw.download_to_raw("o/d", raw_dir, force=True)
    assert fake_download == ["o/d", "o/d"]


def test_export_kaggle_credentials_does_not_override_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "do-ambiente")
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    settings = raw.Settings(kaggle_username="do-env-file", kaggle_key="k", _env_file=None)  # type: ignore[call-arg]
    raw._export_kaggle_credentials(settings)
    import os

    assert os.environ["KAGGLE_USERNAME"] == "do-ambiente"
    assert os.environ["KAGGLE_KEY"] == "k"
    monkeypatch.delenv("KAGGLE_KEY")
