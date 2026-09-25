"""Avaliação do campeão no conjunto de teste inteiro, com o modelo que está carregado.

Complementa as contas escolhidas na interface: duas ou três contas não provam nada (o ganho do modelo é
médio), então mostramos o desempenho em todas as contas-mês do teste, contra o baseline ingênuo.
"""

import logging
import threading
from collections.abc import Callable

import numpy as np
import pandas as pd

from the_bank_project.features import FeatureReader
from the_bank_project.serving.catalog import AccountCatalog
from the_bank_project.serving.model_store import ModelBundle
from the_bank_project.serving.schemas import ErrorStats, EvaluationReport, MonthError, ScatterPoint
from the_bank_project.serving.service import BASELINE, CALENDAR_REFS
from the_bank_project.training.evaluate import regression_metrics

logger = logging.getLogger(__name__)
SCATTER_POINTS = 1_200


def _stats(y: np.ndarray, pred: np.ndarray) -> ErrorStats:
    return ErrorStats(**regression_metrics(y, pred))


def build_report(
    reader: FeatureReader, catalog: AccountCatalog, bundle: ModelBundle, service_refs: list[str], seed: int = 0
) -> EvaluationReport:
    """Prevê todas as contas-mês do teste e compara com o valor real e com a média dos 3 meses."""
    pairs = catalog.pairs("teste")
    entities = pairs[["account_id", "event_timestamp"]].assign(
        event_timestamp=pairs["event_timestamp"].dt.tz_localize("UTC")
    )
    feats = reader.offline(entities, [*service_refs, *CALENDAR_REFS])
    feats["event_timestamp"] = pd.to_datetime(feats["event_timestamp"]).dt.tz_localize(None)
    feats["account_id"] = feats["account_id"].astype(str)
    df = pairs.merge(feats, on=["account_id", "event_timestamp"], how="inner", validate="1:1")
    if len(df) != len(pairs):
        raise ValueError("A feature store não devolveu features para todo o conjunto de teste.")
    pred = np.clip(np.asarray(bundle.model.predict(df[bundle.input_names].astype("float64"))), 0, None)
    y, base = (
        df["actual"].to_numpy(dtype="float64"),
        df[BASELINE].fillna(df["outflow_amount"]).to_numpy(dtype="float64"),
    )
    by_month = [
        MonthError(
            month=pd.Timestamp(m).date(),
            n=int(mask.sum()),
            model_mae=float(np.abs(y[mask] - pred[mask]).mean()),
            baseline_mae=float(np.abs(y[mask] - base[mask]).mean()),
        )
        for m in sorted(df["event_timestamp"].unique())
        for mask in [(df["event_timestamp"] == m).to_numpy()]
    ]
    pick = np.random.default_rng(seed).choice(len(df), size=min(SCATTER_POINTS, len(df)), replace=False)
    window = bundle.info.windows.get("test_window", "")
    return EvaluationReport(
        model_version=bundle.info.version,
        window=window,
        n_rows=len(df),
        model=_stats(y, pred),
        baseline=_stats(y, base),
        win_rate=float((np.abs(y - pred) < np.abs(y - base)).mean()),
        within_20_model=float((np.abs(y - pred) <= 0.2 * y).mean()),
        within_20_baseline=float((np.abs(y - base) <= 0.2 * y).mean()),
        by_month=by_month,
        points=[ScatterPoint(actual=float(y[i]), predicted=float(pred[i]), baseline=float(base[i])) for i in pick],
        axis_max=float(np.percentile(y, 99)),
    )


class EvaluationCache:
    """Calcula o relatório em segundo plano, uma vez por versão do campeão."""

    def __init__(self, compute: Callable[[ModelBundle], EvaluationReport]) -> None:
        self._compute = compute
        self._lock = threading.Lock()
        self._done: dict[str, EvaluationReport] = {}
        self._running: set[str] = set()

    def get(self, version: str) -> EvaluationReport | None:
        return self._done.get(version)

    def start(self, bundle: ModelBundle) -> None:
        """Dispara o cálculo para a versão do `bundle`, se ainda não houver um pronto ou em curso."""
        version = bundle.info.version
        with self._lock:
            if version in self._done or version in self._running:
                return
            self._running.add(version)
        threading.Thread(target=self._run, args=(bundle,), daemon=True, name=f"evaluation-v{version}").start()

    def _run(self, bundle: ModelBundle) -> None:
        version = bundle.info.version
        try:
            report = self._compute(bundle)
            with self._lock:
                self._done[version] = report
            logger.info("Avaliação no teste pronta para a v%s (MAE %.0f).", version, report.model.mae)
        except Exception:
            logger.exception("Falha ao avaliar o campeão v%s no teste.", version)
        finally:
            with self._lock:
                self._running.discard(version)
