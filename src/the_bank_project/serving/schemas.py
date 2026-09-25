"""Contratos de entrada e saída da API (Pydantic)."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Split = Literal["treino", "validacao", "teste", "folga"]  # folga: meses descartados entre os conjuntos


class PredictRequest(BaseModel):
    """Pedido de previsão para uma ou mais contas."""

    account_ids: list[str] = Field(min_length=1, description="Contas a prever (sem repetição).")
    reference_month: date | None = Field(
        default=None,
        description="Mês T cujas features alimentam o modelo. Omitido: o mês mais recente do online store.",
    )
    include_features: bool = Field(default=False, description="Devolve as features usadas em cada previsão.")

    @field_validator("account_ids")
    @classmethod
    def _unique(cls, ids: list[str]) -> list[str]:
        cleaned = [i.strip() for i in ids]
        if any(not i for i in cleaned):
            raise ValueError("account_ids não pode conter valores vazios.")
        return list(dict.fromkeys(cleaned))


class ModelRef(BaseModel):
    """Modelo que gerou as previsões."""

    name: str
    version: str
    algorithm: str


class Prediction(BaseModel):
    """Previsão de saídas do mês seguinte para uma conta."""

    account_id: str
    features_as_of: date = Field(description="Mês T (último dia) das features usadas.")
    target_month: date = Field(description="Mês T+1 (último dia) previsto.")
    predicted_next_month_outflow: float
    actual_next_month_outflow: float | None = Field(default=None, description="Valor real de T+1, se já conhecido.")
    baseline_next_month_outflow: float | None = Field(
        default=None, description="Ingênuo: média das saídas dos 3 meses."
    )
    error: float | None = Field(default=None, description="Previsto menos real.")
    split: Split | None = Field(default=None, description="Conjunto a que o mês T pertence no treino do modelo.")
    features: dict[str, float | None] | None = None


class PredictResponse(BaseModel):
    """Previsões, na ordem do pedido, e as contas sem features."""

    model: ModelRef
    predictions: list[Prediction]
    not_found: list[str]


class AccountInfo(BaseModel):
    """Atributos cadastrais de uma conta (feature view `account_static`)."""

    account_id: str
    district_name: str | None = None
    region: str | None = None
    owner_gender: str | None = None
    frequency: str | None = None
    has_loan: bool | None = None
    has_card: bool | None = None
    dependent_count: int | None = None
    first_month: date | None = None
    last_month: date | None = None


class AccountPage(BaseModel):
    """Página de contas da busca."""

    total: int
    items: list[AccountInfo]


class MonthInfo(BaseModel):
    """Mês de referência disponível para previsão."""

    reference_month: date | None = Field(description="Último dia do mês; nulo = mais recente (futuro).")
    label: str
    split: Split | None
    has_actual: bool
    n_accounts: int


class HistoryPoint(BaseModel):
    """Um mês do histórico de uma conta."""

    month: date
    outflow: float | None
    inflow: float | None
    closing_balance: float | None


class History(BaseModel):
    """Histórico recente de uma conta até o mês T, mais o valor real de T+1 (se conhecido)."""

    account_id: str
    reference_month: date
    points: list[HistoryPoint]
    actual_next_month_outflow: float | None


class ComparisonRow(BaseModel):
    """Um modelo (ou baseline) no comparativo do teste."""

    name: str
    label: str
    kind: Literal["baseline", "candidate"]
    test_mae: float
    champion: bool = False


class ModelInfo(BaseModel):
    """O campeão carregado, seu desempenho e as features que ele usa."""

    name: str
    version: str
    algorithm: str
    algorithm_label: str
    run_id: str
    metrics: dict[str, float]
    skill_vs_naive: float | None
    windows: dict[str, str]
    comparison: list[ComparisonRow]
    features: list[dict[str, Any]]


class ErrorStats(BaseModel):
    """MAE, RMSE e R² de um preditor."""

    mae: float
    rmse: float
    r2: float


class MonthError(BaseModel):
    """Erro médio (MAE) do modelo e do baseline num mês de teste."""

    month: date
    n: int
    model_mae: float
    baseline_mae: float


class ScatterPoint(BaseModel):
    """Uma conta-mês do teste: valor real, previsto e ingênuo."""

    actual: float
    predicted: float
    baseline: float


class EvaluationReport(BaseModel):
    """Desempenho do campeão no conjunto de teste inteiro, recalculado com o modelo carregado."""

    model_version: str
    window: str
    n_rows: int
    model: ErrorStats
    baseline: ErrorStats
    win_rate: float = Field(description="Fração de linhas em que o erro do modelo é menor que o do baseline.")
    within_20_model: float = Field(description="Fração de previsões a até 20% do valor real.")
    within_20_baseline: float = Field(description="Idem, para a média de 3 meses.")
    by_month: list[MonthError]
    points: list[ScatterPoint]
    axis_max: float = Field(description="Limite dos eixos do dispersão (percentil 99 do valor real).")


class EvaluationResponse(BaseModel):
    """`ready=False` enquanto o relatório é calculado (alguns segundos após o modelo carregar)."""

    ready: bool
    report: EvaluationReport | None = None
