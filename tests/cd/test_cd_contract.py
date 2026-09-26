"""Contrato do CD: a matrix do `cd.yml`, o override do GHCR, o compose e o smoke test falam dos mesmos nomes."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGES = {p.parent.name for p in (ROOT / "docker").glob("*/Dockerfile")}


class Loader(yaml.SafeLoader):
    """SafeLoader que aceita a tag `!reset` do Compose (o valor vem como está: `None`)."""


Loader.add_constructor("!reset", lambda loader, node: loader.construct_scalar(node))  # type: ignore[arg-type]


def load(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / name).read_text(), Loader=Loader)  # type: ignore[no-any-return]  # noqa: S506


def local_image(name: str) -> str:
    return f"the-bank-project-{name}:latest"


def test_matrix_covers_every_dockerfile() -> None:
    cd = load(".github/workflows/cd.yml")
    assert set(cd["jobs"]["publish"]["strategy"]["matrix"]["image"]) == IMAGES


def test_cd_only_publishes_after_a_green_ci_on_master() -> None:
    cd = load(".github/workflows/cd.yml")
    trigger = cd[True]  # `on:` vira a chave booleana True no YAML 1.1
    assert trigger["workflow_run"]["workflows"] == ["CI"]
    assert trigger["workflow_run"]["branches"] == ["master"]
    assert "workflow_dispatch" in trigger
    assert "conclusion == 'success'" in cd["jobs"]["publish"]["if"]
    assert cd["permissions"]["packages"] == "write"


def test_cd_smoke_tests_before_pushing() -> None:
    steps = load(".github/workflows/cd.yml")["jobs"]["publish"]["steps"]
    order = [next(k for k in ("uses", "run") if k in s) and (s.get("uses") or s["run"]) for s in steps]
    smoke = next(i for i, s in enumerate(order) if "smoke_image.sh" in s)
    push = next(i for i, s in enumerate(order) if s.startswith("docker push"))
    assert smoke < push


def test_smoke_script_handles_every_image() -> None:
    text = (ROOT / "scripts/smoke_image.sh").read_text()
    assert set(re.findall(r"^\s+(\w+)\)", text, flags=re.M)) - {"*"} == IMAGES


def test_local_compose_images_match_the_dockerfiles() -> None:
    services = load("docker-compose.yml")["services"]
    built = {s["image"] for s in services.values() if "build" in s} | {
        load("docker-compose.yml")["x-airflow-common"]["image"]
    }
    assert built == {local_image(n) for n in IMAGES}


def built_services() -> list[str]:
    """Serviços do compose local que usam imagem do projeto (com `build`, direto ou via `x-airflow-common`)."""
    compose = load("docker-compose.yml")
    ours = {local_image(n) for n in IMAGES}
    return [n for n, s in compose["services"].items() if s.get("image", compose["x-airflow-common"]["image"]) in ours]


def test_ghcr_override_covers_exactly_the_services_we_build() -> None:
    assert set(load("docker-compose.ghcr.yml")["services"]) == set(built_services())


@pytest.mark.parametrize("service", built_services())
def test_ghcr_override_replaces_the_build_with_the_published_image(service: str) -> None:
    override = load("docker-compose.ghcr.yml")["services"][service]
    pattern = r"ghcr\.io/\$\{GHCR_OWNER:-\w+\}/the-bank-project-(airflow|mlflow|serving):\$\{IMAGE_TAG:-latest\}"
    match = re.fullmatch(pattern, override["image"])
    assert match and match.group(1) in IMAGES
