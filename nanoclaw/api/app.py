import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from nanoclaw.api.routers import events, health, messages, sessions, ui
from nanoclaw.api.schemas import ErrorResponse
from nanoclaw.core.agent import create_agent_app
from nanoclaw.core.approval import create_api_approval_callback
from nanoclaw.core.bootstrap import init_core
from nanoclaw.core.config import DB_PATH, PROJECT_ROOT


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if getattr(app.state, "agent_app", None) is not None:
        yield
        return

    env_path = os.path.join(PROJECT_ROOT, ".env")
    load_dotenv(env_path, override=True)
    provider = os.getenv("DEFAULT_PROVIDER", "openai")
    model = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    await init_core(provider, model, asyncio.get_event_loop())

    try:
        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
            app.state.checkpointer = memory
            app.state.agent_app = create_agent_app(
                provider_name=provider,
                model_name=model,
                checkpointer=memory,
            )
            app.state.provider = provider
            app.state.model = model

            approval_callback, pending_approvals = create_api_approval_callback()
            app.state.approval_callback = approval_callback
            app.state.pending_approvals = pending_approvals

            yield
    finally:
        app.state.agent_app = None
        app.state.checkpointer = None
        app.state.approval_callback = None
        app.state.pending_approvals = None


def create_app() -> FastAPI:
    app = FastAPI(title="NanoClaw API Runtime", version="0.1.0", lifespan=lifespan)
    app.state.agent_app = None
    app.state.provider = os.getenv("DEFAULT_PROVIDER", "openai")
    app.state.model = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")

    app.include_router(ui.router)
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(events.router)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        code = "bad_request" if exc.status_code == 400 else "http_error"
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_code=code,
                message=str(exc.detail),
                detail=None,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="internal_server_error",
                message="internal server error",
                detail=str(exc),
            ).model_dump(),
        )

    return app


app = create_app()
