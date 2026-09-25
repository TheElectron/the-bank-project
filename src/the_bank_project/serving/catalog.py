"""Catálogo de contas e meses da interface: quem existe, em que mês há valor real e o conjunto do treino.

Vem dos labels (o futuro conhecido, fora do Feast) e dos atributos cadastrais, que passam pelo Feast.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from the_bank_project.config import SplitConfig
from the_bank_project.features import FeatureReader
from the_bank_project.serving.schemas import AccountInfo, MonthInfo, Split
from the_bank_project.training.labels import TARGET
from the_bank_project.training.split import chronological_split

STATIC_REFS = [
    "account_static:district_name",
    "account_static:district_region",
    "account_static:owner_gender",
    "account_static:account_frequency",
    "account_static:has_loan",
    "account_static:has_card",
    "account_static:dependent_count",
]
SPLIT_NAMES: dict[str, Split] = {"train": "treino", "val": "validacao", "test": "teste"}
MONTH_NAMES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def month_end(value: Any) -> pd.Timestamp:
    """Último dia (à meia-noite) do mês de `value`."""
    return (pd.Timestamp(value) + pd.offsets.MonthEnd(0)).normalize()


def month_label(ts: pd.Timestamp) -> str:
    return f"{MONTH_NAMES[ts.month - 1]}/{ts.year}"


def _none_if_na(value: Any) -> Any:
    return None if pd.isna(value) else value


class AccountCatalog:
    """Consultas em memória sobre contas e meses (4,5 mil contas, 180 mil pares conta x mês)."""

    def __init__(self, labels: pd.DataFrame, static: pd.DataFrame, split: SplitConfig) -> None:
        labels = labels.assign(account_id=labels["account_id"].astype(str))
        self._labels = labels
        self._actual = labels.set_index(["account_id", "event_timestamp"])[TARGET]
        window = chronological_split(labels["event_timestamp"], split)
        self._split_of: dict[pd.Timestamp, Split] = {}
        for month in sorted(labels["event_timestamp"].unique()):
            ts = pd.Timestamp(month)
            hit = [k for k, (a, b) in window.windows.items() if a <= ts <= b]
            self._split_of[ts] = SPLIT_NAMES[hit[0]] if hit else "folga"
        by_month = labels.groupby("event_timestamp")["account_id"]
        self._by_month = {pd.Timestamp(m): sorted(ids, key=int) for m, ids in by_month}
        self._latest_month = max(self._by_month) + pd.offsets.MonthEnd(1)
        span = labels.groupby("account_id")["event_timestamp"].agg(["min", "max"])
        static = static.assign(account_id=static["account_id"].astype(str)).set_index("account_id")
        self._all = sorted(set(static.index) | set(span.index), key=int)
        self._info = {a: self._build_info(a, static, span) for a in self._all}

    @staticmethod
    def _build_info(account_id: str, static: pd.DataFrame, span: pd.DataFrame) -> AccountInfo:
        row = static.loc[account_id].to_dict() if account_id in static.index else {}
        get = {k: _none_if_na(v) for k, v in row.items()}.get
        has_loan, has_card, dependents = get("has_loan"), get("has_card"), get("dependent_count")
        has_span = account_id in span.index
        return AccountInfo(
            account_id=account_id,
            district_name=get("district_name"),
            region=get("district_region"),
            owner_gender=get("owner_gender"),
            frequency=get("account_frequency"),
            has_loan=None if has_loan is None else bool(has_loan),
            has_card=None if has_card is None else bool(has_card),
            dependent_count=None if dependents is None else int(dependents),
            first_month=span.loc[account_id, "min"].date() if has_span else None,
            last_month=span.loc[account_id, "max"].date() if has_span else None,
        )

    @property
    def n_accounts(self) -> int:
        return len(self._all)

    @property
    def latest_month(self) -> pd.Timestamp:
        """Mês mais recente com features (o seguinte ao último com valor real)."""
        return self._latest_month

    def months(self) -> list[MonthInfo]:
        """Mais recente primeiro: o mês futuro (sem valor real) e depois os meses com valor real."""
        latest = MonthInfo(reference_month=None, label=f"Mais recente ({month_label(self._latest_month)})",
                           split=None, has_actual=False, n_accounts=self.n_accounts)  # fmt: skip
        history = [
            MonthInfo(
                reference_month=m.date(),
                label=month_label(m),
                split=self._split_of[m],
                has_actual=True,
                n_accounts=len(self._by_month[m]),
            )  # fmt: skip
            for m in sorted(self._by_month, reverse=True)
        ]
        return [latest, *history]

    def pairs(self, split: Split) -> pd.DataFrame:
        """Pares (conta, mês T) do conjunto `split`, com o valor real de T+1 em `actual`."""
        keep = self._labels["event_timestamp"].map(self._split_of) == split
        return self._labels.loc[keep].rename(columns={TARGET: "actual"}).reset_index(drop=True)

    def has_month(self, month: pd.Timestamp) -> bool:
        return month in self._by_month

    def split_of(self, month: pd.Timestamp) -> Split | None:
        return self._split_of.get(month)

    def actual(self, account_id: str, month: pd.Timestamp) -> float | None:
        """Saídas reais de `month` + 1, se conhecidas."""
        value = self._actual.get((account_id, month))
        return None if value is None or pd.isna(value) else float(value)

    def info(self, account_id: str) -> AccountInfo | None:
        return self._info.get(account_id)

    def _pool(self, month: pd.Timestamp | None) -> list[str]:
        return self._all if month is None else self._by_month.get(month, [])

    def search(self, month: pd.Timestamp | None, query: str, limit: int, offset: int) -> tuple[int, list[AccountInfo]]:
        """Contas disponíveis no mês (todas se `month` é nulo) cujo id contém `query`, por id numérico."""
        pool = self._pool(month)
        hits = [a for a in pool if query in a] if query else pool
        return len(hits), [self._info[a] for a in hits[offset : offset + limit]]

    def sample(self, month: pd.Timestamp | None, n: int, seed: int | None = None) -> list[AccountInfo]:
        """`n` contas sorteadas entre as disponíveis no mês."""
        pool = self._pool(month)
        picks: Sequence[int] = (
            np.random.default_rng(seed).choice(len(pool), size=min(n, len(pool)), replace=False).tolist()
            if pool
            else []
        )
        return [self._info[pool[i]] for i in sorted(picks)]


def load_catalog(reader: FeatureReader, labels: pd.DataFrame, split: SplitConfig) -> AccountCatalog:
    """Monta o catálogo: os atributos de todas as contas vêm do online store."""
    ids = sorted(labels["account_id"].astype(str).unique(), key=int)
    return AccountCatalog(labels, reader.online(ids, STATIC_REFS), split)
