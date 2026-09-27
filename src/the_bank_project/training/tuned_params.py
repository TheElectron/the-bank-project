"""Hiperparâmetros ajustados (`configs/best_params.yaml`): schema, leitura e escrita.

Fica separado do `tuning.py` para o treino em produção (Airflow) ler o arquivo sem depender do Optuna.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from the_bank_project.config import CONFIGS_DIR, GlobalConfig
from the_bank_project.training.models import Params

logger = logging.getLogger(__name__)


class TunedModel(BaseModel):
    """Melhor configuração de um modelo e o quanto ela ganhou da padrão, medidos nas mesmas dobras."""

    params: Params
    cv_mae: float
    default_cv_mae: float
    n_trials: int
    source: Literal["tuned", "default"]  # "default": nenhuma tentativa bateu a configuração padrão


class BestParams(BaseModel):
    """Resultado do `make tune`; o `train` usa `models[algoritmo].params` no lugar do sorteio simples."""

    generated_at: datetime
    seed: int
    log_target: bool
    cv_folds: int
    tuned_window: str  # meses de treino usados nas dobras (validação e teste ficam de fora)
    models: dict[str, TunedModel]


def best_params_path(cfg: GlobalConfig) -> Path:
    """`tuning.best_params_file`: relativo a `configs/`, ou absoluto."""
    return CONFIGS_DIR / cfg.tuning.best_params_file


def save_best_params(best: BestParams, path: Path) -> None:
    """Grava o YAML (legível e versionável)."""
    header = "# Gerado por `make tune` (Fase 9a). Lido pelo `train`; não editar à mão.\n"
    path.write_text(header + yaml.safe_dump(best.model_dump(mode="json"), sort_keys=False), encoding="utf-8")


def load_best_params(cfg: GlobalConfig) -> BestParams | None:
    """Lê os parâmetros ajustados; None se ainda não houve tuning ou se não valem para a config atual.

    Raises:
        pydantic.ValidationError: se o arquivo existir mas estiver fora do schema.
    """
    path = best_params_path(cfg)
    if not path.exists():
        return None
    best = BestParams.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if best.log_target != cfg.training.log_target:
        logger.warning("%s foi ajustado com log_target=%s (config: %s); ignorando.", path.name, best.log_target,
                       cfg.training.log_target)  # fmt: skip
        return None
    return best
