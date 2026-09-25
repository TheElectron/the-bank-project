"""Endpoints: contrato público (`/predict`), operação (`/health`, `/metrics`) e apoio à interface (`/api/*`)."""

from datetime import date
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from the_bank_project.serving.catalog import month_end
from the_bank_project.serving.model_store import ModelBundle
from the_bank_project.serving.schemas import (
    AccountInfo,
    AccountPage,
    EvaluationResponse,
    History,
    ModelInfo,
    MonthInfo,
    PredictRequest,
    PredictResponse,
)
from the_bank_project.serving.state import AppState

router = APIRouter()


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.s
    return state


def get_bundle(state: Annotated[AppState, Depends(get_state)]) -> ModelBundle:
    """O campeão carregado; 503 enquanto não houver um com o alias `champion`."""
    bundle = state.models.bundle
    if bundle is None:
        raise HTTPException(503, "Nenhum modelo com o alias 'champion' está registrado. Rode o treino e o gate.")
    return bundle


State = Annotated[AppState, Depends(get_state)]
Bundle = Annotated[ModelBundle, Depends(get_bundle)]


def _month(value: date | None) -> pd.Timestamp | None:
    return None if value is None else month_end(value)


def _account_or_404(state: AppState, account_id: str) -> AccountInfo:
    info = state.catalog.info(account_id)
    if info is None:
        raise HTTPException(404, f"Conta {account_id} não encontrada.")
    return info


# --- contrato público ---


@router.post("/predict", response_model=PredictResponse, tags=["previsão"])
def predict(body: PredictRequest, state: State, bundle: Bundle) -> PredictResponse:
    """Previsão de saídas do mês seguinte. Sem `reference_month`, usa as features mais recentes (online store)."""
    if len(body.account_ids) > state.cfg.serving.max_batch:
        raise HTTPException(422, f"No máximo {state.cfg.serving.max_batch} contas por chamada.")
    return state.service.predict(bundle, body.account_ids, _month(body.reference_month), body.include_features)


# --- operação ---


@router.get("/health", tags=["operação"])
def health(state: State, response: Response) -> dict[str, Any]:
    """Estado da API: campeão carregado e tamanho do catálogo. 503 se não houver modelo."""
    bundle = state.models.bundle
    if bundle is None:
        response.status_code = 503
    model = None if bundle is None else bundle.info
    return {
        "status": "ok" if bundle else "sem_modelo",
        "model": None
        if model is None
        else {"name": model.name, "version": model.version, "algorithm": model.algorithm},
        "accounts": state.catalog.n_accounts,
        "latest_month": state.catalog.latest_month.date().isoformat(),
    }


@router.get("/metrics", tags=["operação"])
def metrics(state: State) -> Response:
    """Métricas no formato Prometheus."""
    return Response(state.metrics.render(), media_type="text/plain; version=0.0.4")


# --- apoio à interface ---


@router.get("/api/model", response_model=ModelInfo, tags=["interface"])
def model(bundle: Bundle) -> ModelInfo:
    """O campeão, seu desempenho no teste (contra os baselines) e as features que usa."""
    return bundle.info


@router.get("/api/evaluation", response_model=EvaluationResponse, tags=["interface"])
def evaluation(state: State, bundle: Bundle) -> EvaluationResponse:
    """Desempenho do campeão em todo o conjunto de teste (calculado em segundo plano após a carga do modelo)."""
    report = state.evaluation.get(bundle.info.version)
    return EvaluationResponse(ready=report is not None, report=report)


@router.get("/api/months", response_model=list[MonthInfo], tags=["interface"])
def months(state: State) -> list[MonthInfo]:
    """Meses de referência disponíveis, com o conjunto do treino a que cada um pertence."""
    return state.catalog.months()


@router.get("/api/accounts", response_model=AccountPage, tags=["interface"])
def accounts(
    state: State,
    reference_month: date | None = None,
    search: str = "",
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AccountPage:
    """Busca contas disponíveis no mês (todas, se omitido) cujo id contém `search`."""
    total, items = state.catalog.search(_month(reference_month), search.strip(), limit, offset)
    return AccountPage(total=total, items=items)


@router.get("/api/accounts/sample", response_model=list[AccountInfo], tags=["interface"])
def sample(
    state: State, reference_month: date | None = None, n: int = Query(5, ge=1, le=50), seed: int | None = None
) -> list[AccountInfo]:
    """Contas sorteadas entre as disponíveis no mês."""
    return state.catalog.sample(_month(reference_month), n, seed)


@router.get("/api/accounts/{account_id}", response_model=AccountInfo, tags=["interface"])
def account(account_id: str, state: State) -> AccountInfo:
    """Atributos cadastrais da conta."""
    return _account_or_404(state, account_id)


@router.get("/api/accounts/{account_id}/history", response_model=History, tags=["interface"])
def history(
    account_id: str, state: State, reference_month: date, months: int | None = Query(None, ge=1, le=36)
) -> History:
    """Entradas, saídas e saldo até o mês T e o valor real de T+1, quando conhecido."""
    _account_or_404(state, account_id)
    return state.service.history(account_id, pd.Timestamp(reference_month), months or state.cfg.serving.history_months)
