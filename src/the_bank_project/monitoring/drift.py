"""Drift de dados: compara as features do treino com as dos meses mais recentes (Evidently).

O dataset é histórico, então o "dado atual" é um replay temporal: a referência são os meses que o
modelo viu (treino + validação) e a janela atual são os últimos meses da Gold, que caem no teste.
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from pydantic import BaseModel

from the_bank_project.config import GlobalConfig, MonitoringConfig
from the_bank_project.training.dataset import Dataset, load_dataset
from the_bank_project.training.split import Split, chronological_split

if TYPE_CHECKING:
    from evidently.core.report import Snapshot

logger = logging.getLogger(__name__)

REPORT_FILE = "drift_report.html"
SUMMARY_FILE = "drift_summary.json"


class FeatureDrift(BaseModel):
    """Drift de uma feature: distância de Wasserstein normalizada pelo desvio da referência."""

    score: float
    drifted: bool


class DriftSummary(BaseModel):
    """Resultado do drift, gravado em JSON (e lido pelas etapas seguintes do pipeline)."""

    reference_window: str
    current_window: str
    reference_rows: int
    current_rows: int
    n_features: int
    n_drifted: int
    drift_share: float
    drift_detected: bool
    feature_threshold: float
    drift_share_threshold: float
    features: dict[str, FeatureDrift]
    generated_at: datetime | None = None


def load_summary(out_dir: Path) -> DriftSummary:
    """Lê o resumo gravado por `run_drift`.

    Raises:
        FileNotFoundError: se o drift ainda não foi calculado.
    """
    path = out_dir / SUMMARY_FILE
    if not path.exists():
        raise FileNotFoundError(f"{path} não existe. Calcule o drift antes (`make drift`).")
    return DriftSummary.model_validate_json(path.read_text(encoding="utf-8"))


def select_windows(ds: Dataset, split: Split, current_months: int) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    """Referência (treino + validação) e janela atual (os `current_months` últimos meses do dataset).

    Returns:
        Features da referência, features da janela atual e a descrição legível de cada janela.

    Raises:
        ValueError: se `current_months` for inválido ou a janela atual invadir a referência.
    """
    months = pd.Series(ds.timestamps.unique()).sort_values()
    if not 1 <= current_months <= len(months):
        raise ValueError(f"current_months={current_months} fora de 1..{len(months)} meses disponíveis.")
    current_mask = ds.timestamps.isin(months.iloc[-current_months:]).to_numpy()
    reference_mask = split.train | split.val
    if (current_mask & reference_mask).any():
        raise ValueError("A janela atual invade os meses de treino/validação; reduza `current_months`.")
    ref_start, ref_end = ds.timestamps[reference_mask].min(), ds.timestamps[reference_mask].max()
    cur_start, cur_end = ds.timestamps[current_mask].min(), ds.timestamps[current_mask].max()
    return (
        ds.X[reference_mask],
        ds.X[current_mask],
        f"{ref_start.date()}..{ref_end.date()}",
        f"{cur_start.date()}..{cur_end.date()}",
    )


def compute_drift(
    reference: pd.DataFrame, current: pd.DataFrame, cfg: MonitoringConfig
) -> tuple["Snapshot", DriftSummary]:
    """Drift por feature (Wasserstein normalizada) e no dataset (fração de features com drift).

    Returns:
        O relatório do Evidently (para o HTML) e o resumo. As janelas ficam vazias no resumo:
            quem as conhece (`run_drift`) as preenche.

    Raises:
        ValueError: se alguma janela estiver vazia ou as colunas não baterem.
    """
    if reference.empty or current.empty:
        raise ValueError("Referência e janela atual precisam ter linhas.")
    if set(reference.columns) != set(current.columns):
        raise ValueError("Referência e janela atual precisam ter as mesmas colunas.")
    os.environ.setdefault("DO_NOT_TRACK", "1")  # desliga a telemetria de uso do Evidently
    # importado aqui, depois do DO_NOT_TRACK
    from evidently import Dataset as EvidentlyDataset
    from evidently import Report
    from evidently.presets import DataDriftPreset

    preset = DataDriftPreset(
        drift_share=cfg.drift_share_threshold, num_method="wasserstein", num_threshold=cfg.feature_threshold
    )
    snapshot = Report([preset]).run(EvidentlyDataset.from_pandas(current), EvidentlyDataset.from_pandas(reference))
    scores = {
        m["config"]["column"]: float(m["value"])
        for m in snapshot.dict()["metrics"]
        if m["config"]["type"].endswith(":ValueDrift")
    }
    features = {c: FeatureDrift(score=s, drifted=s > cfg.feature_threshold) for c, s in scores.items()}
    n_drifted = sum(f.drifted for f in features.values())
    share = n_drifted / len(features)
    summary = DriftSummary(
        reference_window="", current_window="", reference_rows=len(reference), current_rows=len(current),
        n_features=len(features), n_drifted=n_drifted, drift_share=share,
        drift_detected=share >= cfg.drift_share_threshold, feature_threshold=cfg.feature_threshold,
        drift_share_threshold=cfg.drift_share_threshold, features=features,
    )  # fmt: skip
    return snapshot, summary


def run_drift(cfg: GlobalConfig, dataset: Dataset | None = None, out_dir: Path | None = None) -> DriftSummary:
    """Calcula o drift (referência x últimos meses) e grava o relatório HTML e o resumo JSON.

    Args:
        cfg: configuração global.
        dataset: dataset já carregado (padrão: labels + features do Feast, como no treino).
        out_dir: onde gravar (padrão: `data/monitoring/`).
    """
    ds = dataset or load_dataset(cfg.paths.gold, cfg.training.feature_service, cfg.feast.repo)
    split = chronological_split(ds.timestamps, cfg.training.split)
    reference, current, ref_window, cur_window = select_windows(ds, split, cfg.monitoring.current_months)
    snapshot, summary = compute_drift(reference, current, cfg.monitoring)
    summary = summary.model_copy(
        update={"reference_window": ref_window, "current_window": cur_window, "generated_at": datetime.now(UTC)}
    )
    out = out_dir or cfg.paths.monitoring
    out.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(out / REPORT_FILE))
    (out / SUMMARY_FILE).write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        "Drift %s: %d/%d features (%.0f%%) com drift | referência %s x atual %s | %s",
        "DETECTADO" if summary.drift_detected else "não detectado", summary.n_drifted, summary.n_features,
        100 * summary.drift_share, ref_window, cur_window, out,
    )  # fmt: skip
    return summary
