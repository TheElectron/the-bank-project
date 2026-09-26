"""Decisão de re-treino por drift: função pura + estado do cooldown em disco.

O estado fica em `data/monitoring/` (não no banco do Airflow) porque a task roda num venv sem acesso a ele.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from the_bank_project.config import GlobalConfig, MonitoringConfig
from the_bank_project.monitoring.drift import DriftSummary, load_summary

logger = logging.getLogger(__name__)

STATE_FILE = "last_retrain.json"
Reason = Literal["retrain", "no_drift", "cooldown", "disabled"]


class RetrainDecision(BaseModel):
    """Se o drift deve disparar o re-treino, e por quê."""

    retrain: bool
    reason: Reason


def should_retrain(
    summary: DriftSummary, last_retrain_at: datetime | None, now: datetime, cfg: MonitoringConfig
) -> RetrainDecision:
    """Decide o re-treino: exige drift no dataset e cooldown vencido (no dia exato do vencimento já libera)."""
    if not cfg.retrain_enabled:
        return RetrainDecision(retrain=False, reason="disabled")
    if not summary.drift_detected:
        return RetrainDecision(retrain=False, reason="no_drift")
    if last_retrain_at is not None and now - last_retrain_at < timedelta(days=cfg.retrain_cooldown_days):
        return RetrainDecision(retrain=False, reason="cooldown")
    return RetrainDecision(retrain=True, reason="retrain")


def load_last_retrain(out_dir: Path) -> datetime | None:
    """Momento do último re-treino disparado por drift, ou None se nunca houve."""
    path = out_dir / STATE_FILE
    if not path.exists():
        return None
    return datetime.fromisoformat(json.loads(path.read_text())["triggered_at"])


def record_retrain(out_dir: Path, now: datetime) -> None:
    """Grava o disparo (inicia o cooldown)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / STATE_FILE).write_text(json.dumps({"triggered_at": now.isoformat()}))


def decide_retrain(cfg: GlobalConfig, now: datetime | None = None, record: bool = True) -> RetrainDecision:
    """Lê o último resumo e o estado do cooldown; com `record`, um "retrain" já inicia o cooldown.

    O cooldown é gravado na decisão, não após o disparo: se o disparo falhar, o próximo é só após o cooldown
    (ou removendo `last_retrain.json`).

    Raises:
        FileNotFoundError: se o drift ainda não foi calculado.
    """
    now = now or datetime.now(UTC)
    out_dir = cfg.paths.monitoring
    decision = should_retrain(load_summary(out_dir), load_last_retrain(out_dir), now, cfg.monitoring)
    if decision.retrain and record:
        record_retrain(out_dir, now)
    logger.info("Re-treino por drift: %s (%s).", "DISPARAR" if decision.retrain else "não disparar", decision.reason)
    return decision
