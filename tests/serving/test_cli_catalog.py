import importlib.util
from types import ModuleType

import pytest

from the_bank_project.config import PROJECT_ROOT
from the_bank_project.serving import cli
from the_bank_project.serving.feature_catalog import FEATURES, GROUPS


def _service_features() -> set[str]:
    spec = importlib.util.spec_from_file_location("defs", PROJECT_ROOT / "feature_repo" / "features.py")
    assert spec and spec.loader
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f.name for p in module.outflow_regression.feature_view_projections for f in p.features}


def test_feature_catalog_covers_exactly_the_regression_service():
    """Contrato: mudou o FeatureService, a interface precisa saber nomear a feature."""
    assert set(FEATURES) == _service_features()
    assert {f.group for f in FEATURES.values()} == set(GROUPS)
    assert all(f.label and f.help and f.unit in {"money", "count", "pct"} for f in FEATURES.values())


def test_cli_starts_uvicorn_with_config_host_and_port(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.append({"app": app, **kw}))
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    assert cli.main(["--port", "9001"]) == 0
    assert (
        calls[0]["app"] == "the_bank_project.serving.app:create_app"
        and calls[0]["factory"] is True
        and calls[0]["port"] == 9001
    )
