"""
    Estado do monitoramento
    Este módulo contém as funções que leem o último resumo de drift e o último re-treino para a interface,
    sem recalcular nada.

    Os arquivos são gravados pela DAG `monitoring` em `data/monitoring/` (a API os monta somente leitura).
"""

import logging

from the_bank_project.config import GlobalConfig
from the_bank_project.monitoring import load_last_retrain, load_summary
from the_bank_project.serving.schemas import DriftedFeature, MonitoringStatus

logger = logging.getLogger(__name__)
TOP_DRIFTED = 5


def read_status(cfg: GlobalConfig) -> MonitoringStatus:
    """
        `available=False` se o drift ainda não rodou (ou se o arquivo estiver ilegível: a interface segue sem ele).
    """
    out_dir = cfg.paths.monitoring
    try:
        summary = load_summary(out_dir)
        last_retrain = load_last_retrain(out_dir)
    except FileNotFoundError:
        return MonitoringStatus(available=False)
    except Exception:
        logger.exception("Resumo de drift ilegível em %s.", out_dir)
        return MonitoringStatus(available=False)
    drifted = sorted(((n, f.score) for n, f in summary.features.items() if f.drifted), key=lambda x: -x[1])
    return MonitoringStatus(
        available=True, drift_detected=summary.drift_detected, n_features=summary.n_features,
        n_drifted=summary.n_drifted, drift_share=summary.drift_share,
        drift_share_threshold=summary.drift_share_threshold, reference_window=summary.reference_window,
        current_window=summary.current_window, generated_at=summary.generated_at, last_retrain_at=last_retrain,
        top_drifted=[DriftedFeature(name=n, score=s) for n, s in drifted[:TOP_DRIFTED]],
    )  # fmt: skip
