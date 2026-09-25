"""Lógica de previsão: features (Feast) → modelo → resposta. Sem HTTP, testável isolada."""

import numpy as np
import pandas as pd

from the_bank_project.features import FeatureReader
from the_bank_project.serving.catalog import AccountCatalog, month_end
from the_bank_project.serving.metrics import ServingMetrics
from the_bank_project.serving.model_store import ContractError, ModelBundle
from the_bank_project.serving.schemas import History, HistoryPoint, ModelRef, Prediction, PredictResponse

CALENDAR_REFS = ["account_monthly:year", "account_monthly:month"]
HISTORY_REFS = ["account_monthly:outflow_amount", "account_monthly:inflow_amount", "account_monthly:closing_balance"]
BASELINE = "outflow_3m_avg"  # o melhor baseline ingênuo do treino: média das saídas dos 3 meses


class UnknownMonth(LookupError):
    """O mês pedido não tem features com valor real conhecido."""


class PredictionService:
    """Busca as features no Feast, alinha às colunas do modelo e prediz."""

    def __init__(self, reader: FeatureReader, catalog: AccountCatalog, metrics: ServingMetrics) -> None:
        self._reader, self._catalog, self._metrics = reader, catalog, metrics
        self._service_refs = reader.service_features()

    @property
    def service_refs(self) -> list[str]:
        return self._service_refs

    def _features(self, ids: list[str], month: pd.Timestamp | None) -> pd.DataFrame:
        """Uma linha por conta encontrada, com as features do FeatureService e `year`/`month` de T."""
        refs = [*self._service_refs, *CALENDAR_REFS]
        if month is None:
            df = self._reader.online(ids, refs)
        else:
            if not self._catalog.has_month(month):
                raise UnknownMonth(f"Sem dados para o mês {month.date()}.")
            entities = pd.DataFrame({"account_id": ids, "event_timestamp": month.tz_localize("UTC")})
            df = self._reader.offline(entities, refs)
        df["account_id"] = df["account_id"].astype(str)
        return df[df["year"].notna()].set_index("account_id")

    def predict(
        self, bundle: ModelBundle, account_ids: list[str], reference_month: pd.Timestamp | None, include_features: bool
    ) -> PredictResponse:
        """Previsão de saídas de T+1 para cada conta. `reference_month` nulo usa o mês mais recente do online store."""
        month = None if reference_month is None else month_end(reference_month)
        self._metrics.predict_requests.labels(mode="online" if month is None else "historico").inc()
        feats = self._features(account_ids, month)
        found = [a for a in account_ids if a in feats.index]
        not_found = [a for a in account_ids if a not in feats.index]
        self._metrics.accounts_not_found.inc(len(not_found))
        predictions: list[Prediction] = []
        if found:
            missing = [c for c in bundle.input_names if c not in feats.columns]
            if missing:
                raise ContractError(f"A feature store não devolveu as features do modelo: {missing}")
            X = feats.loc[found, bundle.input_names].astype("float64")
            raw = np.asarray(bundle.model.predict(X), dtype="float64")
            values = np.clip(raw, 0, None)  # saídas não são negativas (a linear pode extrapolar)
            for account_id, value in zip(found, values, strict=True):
                row = feats.loc[account_id]
                t = month_end(pd.Timestamp(year=int(row["year"]), month=int(row["month"]), day=1))
                actual = self._catalog.actual(account_id, t)
                baseline = None if pd.isna(row[BASELINE]) else float(row[BASELINE])
                predictions.append(
                    Prediction(
                        account_id=account_id,
                        features_as_of=t.date(),
                        target_month=(t + pd.offsets.MonthEnd(1)).date(),
                        predicted_next_month_outflow=float(value),
                        actual_next_month_outflow=actual,
                        baseline_next_month_outflow=baseline,
                        error=None if actual is None else float(value) - actual,
                        split=self._catalog.split_of(t),
                        features=(
                            {c: (None if pd.isna(row[c]) else float(row[c])) for c in bundle.input_names}
                            if include_features
                            else None
                        ),
                    )
                )
                self._metrics.predicted_value.observe(float(value))
        self._metrics.predictions.inc(len(predictions))
        info = bundle.info
        return PredictResponse(
            model=ModelRef(name=info.name, version=info.version, algorithm=info.algorithm),
            predictions=predictions,
            not_found=not_found,
        )

    def history(self, account_id: str, reference_month: pd.Timestamp, months: int) -> History:
        """Entradas, saídas e saldo dos `months` meses até T (inclusive) e o valor real de T+1, se conhecido."""
        month = month_end(reference_month)
        stamps = [month - pd.offsets.MonthEnd(k) for k in range(months)]
        entities = pd.DataFrame({"account_id": account_id, "event_timestamp": [s.tz_localize("UTC") for s in stamps]})
        df = self._reader.offline(entities, HISTORY_REFS)
        df["event_timestamp"] = pd.to_datetime(df["event_timestamp"]).dt.tz_localize(None).dt.normalize()
        df = df.sort_values("event_timestamp")
        points = [
            HistoryPoint(
                month=r.event_timestamp.date(),
                outflow=None if pd.isna(r.outflow_amount) else float(r.outflow_amount),
                inflow=None if pd.isna(r.inflow_amount) else float(r.inflow_amount),
                closing_balance=None if pd.isna(r.closing_balance) else float(r.closing_balance),
            )
            for r in df.itertuples()
        ]
        return History(
            account_id=account_id,
            reference_month=month.date(),
            points=points,
            actual_next_month_outflow=self._catalog.actual(account_id, month),
        )
