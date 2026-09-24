"""Único ponto de acesso às features (Feast): treino (offline) e serving (online)."""

from the_bank_project.features.store import (
    apply_repo,
    get_offline_features,
    get_online_features,
    materialize_all,
    open_store,
)

__all__ = ["apply_repo", "get_offline_features", "get_online_features", "materialize_all", "open_store"]
