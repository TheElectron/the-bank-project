"""Aplicação FastAPI: ciclo de vida, métricas HTTP, tratamento de erros e a interface web em `/`."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from the_bank_project.config import GlobalConfig, load_config
from the_bank_project.serving.model_store import ContractError
from the_bank_project.serving.routes import router
from the_bank_project.serving.service import UnknownMonth
from the_bank_project.serving.state import AppState, build_state, poll_champion, refresh_champion

STATIC_DIR = Path(__file__).parent / "static"
UNMEASURED_PATHS = {"/metrics", "/static"}


def create_app(cfg: GlobalConfig | None = None, state: AppState | None = None) -> FastAPI:
    """Fábrica da aplicação. `state` injetado dispensa MLflow e Feast (testes)."""
    cfg = cfg or (state.cfg if state else load_config())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        current: AppState = state if state is not None else await asyncio.to_thread(build_state, cfg)
        await asyncio.to_thread(refresh_champion, current)
        app.state.s = current
        poller = asyncio.create_task(poll_champion(current)) if current.cfg.serving.model_poll_seconds > 0 else None
        yield
        if poller:
            poller.cancel()

    app = FastAPI(
        title="The Bank Project — previsão de saídas",
        description="Prevê as saídas totais de uma conta no mês seguinte (campeão do MLflow + features do Feast).",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def measure(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Conta e cronometra as requisições, rotulando pelo *template* da rota (poucos rótulos distintos)."""
        started = time.perf_counter()
        response = await call_next(request)
        path = getattr(request.scope.get("route"), "path", "não-encontrada")
        current: AppState | None = getattr(request.app.state, "s", None)
        if current is not None and path not in UNMEASURED_PATHS:
            current.metrics.http_requests.labels(request.method, path, str(response.status_code)).inc()
            current.metrics.http_latency.labels(path).observe(time.perf_counter() - started)
        return response

    @app.exception_handler(ContractError)
    async def contract_error(_: Request, exc: ContractError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(UnknownMonth)
    async def unknown_month(_: Request, exc: UnknownMonth) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
