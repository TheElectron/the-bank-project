"""Tuning com Optuna: espaço de busca, uso só dos meses de treino, escolha contra a configuração padrão."""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from the_bank_project.config import GlobalConfig
from the_bank_project.training import tuning
from the_bank_project.training.dataset import Dataset
from the_bank_project.training.models import CANDIDATES, Candidate
from the_bank_project.training.split import chronological_split
from the_bank_project.training.tuned_params import BestParams
from the_bank_project.training.tuning import run_tuning, suggest

DAY = date(2026, 9, 26)
XGB = next(c for c in CANDIDATES if c.name == "xgboost")
FAST = Candidate(  # o mesmo algoritmo com árvores pequenas: o que se testa é a orquestração, não o ajuste
    XGB.name, XGB.build, defaults={**XGB.defaults, "n_estimators": 30},
    tune_space={"n_estimators": ("int", 10, 30), "max_depth": ("int", 2, 4)},
)  # fmt: skip


class FakeTrial:
    """Grava o que o Optuna receberia, sem sortear."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def suggest_int(self, name: str, lo: int, hi: int) -> int:
        self.calls.append((name, ("int", lo, hi)))
        return lo

    def suggest_float(self, name: str, lo: float, hi: float, log: bool = False) -> float:
        self.calls.append((name, ("log" if log else "float", lo, hi)))
        return lo

    def suggest_categorical(self, name: str, choices: list[Any]) -> Any:
        self.calls.append((name, ("cat", tuple(choices))))
        return choices[0]


def test_suggest_covers_every_kind_of_space() -> None:
    trial = FakeTrial()
    space = {"a": ("int", 1, 5), "b": ("float", 0.1, 0.9), "c": ("log", 1e-3, 1.0), "d": ("cat", ["x", "y"])}
    assert suggest(trial, space) == {"a": 1, "b": 0.1, "c": 1e-3, "d": "x"}  # type: ignore[arg-type]
    assert [k for _, (k, *_) in trial.calls] == ["int", "float", "log", "cat"]


def test_suggest_rejects_unknown_kinds() -> None:
    with pytest.raises(ValueError, match="desconhecido"):
        suggest(FakeTrial(), {"a": ("weird", 1, 2)})  # type: ignore[arg-type]


def test_every_tunable_candidate_has_a_space_that_contains_its_defaults() -> None:
    tunable = [c for c in CANDIDATES if c.tune_space]
    assert {c.name for c in tunable} == {"random_forest", "gradient_boosting", "xgboost"}
    for c in tunable:
        assert set(c.tune_space) >= set(c.defaults), c.name  # o que o treino padrão usa também é ajustável
        for name, value in c.defaults.items():
            kind, *args = c.tune_space[name]
            assert args[0] <= value <= args[1], (c.name, name)


@pytest.fixture
def small_tuning(monkeypatch: pytest.MonkeyPatch, cfg: GlobalConfig) -> GlobalConfig:
    monkeypatch.setattr(tuning, "CANDIDATES", (FAST,))
    cfg.tuning.n_trials, cfg.tuning.cv_folds, cfg.tuning.timeout_minutes = 3, 3, 5
    cfg.tuning.best_params_file = str(cfg.paths.data / "best_params.yaml")  # absoluto: nunca toca o repositório
    return cfg


def test_run_tuning_writes_best_params_never_worse_than_the_default(
    small_tuning: GlobalConfig, dataset: Dataset
) -> None:
    best = run_tuning(small_tuning, dataset, DAY)
    model = best.models["xgboost"]
    assert model.n_trials == 3 and model.cv_mae <= model.default_cv_mae
    assert model.source in {"tuned", "default"}
    assert (model.source == "default") == (model.params == FAST.defaults)
    saved = BestParams.model_validate(yaml.safe_load(Path(small_tuning.tuning.best_params_file).read_text()))
    assert saved == best and saved.cv_folds == 3 and saved.seed == small_tuning.training.seed


def test_folds_only_use_training_months(
    small_tuning: GlobalConfig, dataset: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validação e teste do split não podem aparecer em nenhuma dobra (senão o campeão sai enviesado)."""
    seen: list[np.ndarray] = []
    real: Callable[..., tuple[float, list[float]]] = tuning.cv_mae

    def spy(cand: Candidate, params: dict[str, Any], ds: Dataset, folds: list[Any], cfg: GlobalConfig) -> Any:
        seen.extend(m for pair in folds for m in pair)
        return real(cand, params, ds, folds, cfg)

    monkeypatch.setattr(tuning, "cv_mae", spy)
    run_tuning(small_tuning, dataset, DAY)
    split = chronological_split(dataset.timestamps, small_tuning.training.split)
    outside = ~split.train
    assert seen and not any((m & outside).any() for m in seen)


def test_default_is_kept_when_no_trial_beats_it(
    small_tuning: GlobalConfig, dataset: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = iter([1000.0] + [2000.0] * 10)  # 1ª chamada = configuração padrão; as tentativas são piores
    monkeypatch.setattr(tuning, "cv_mae", lambda *a, **k: (next(calls), [0.0]))
    model = run_tuning(small_tuning, dataset, DAY).models["xgboost"]
    assert (model.source, model.params, model.cv_mae, model.default_cv_mae) == (
        "default",
        FAST.defaults,
        1000.0,
        1000.0,
    )


def test_tuned_params_win_when_a_trial_is_better(
    small_tuning: GlobalConfig, dataset: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = iter([2000.0] + [1500.0] * 10)
    monkeypatch.setattr(tuning, "cv_mae", lambda *a, **k: (next(calls), [0.0]))
    model = run_tuning(small_tuning, dataset, DAY).models["xgboost"]
    assert model.source == "tuned" and model.cv_mae == 1500.0 and model.default_cv_mae == 2000.0
    assert set(model.params) >= set(FAST.defaults)  # a config final é sempre completa (padrão + ajustes)


def test_too_few_training_months_fail_clearly(small_tuning: GlobalConfig, dataset: Dataset) -> None:
    small_tuning.tuning.cv_folds = 30
    with pytest.raises(ValueError, match="não bastam"):
        run_tuning(small_tuning, dataset, DAY)
