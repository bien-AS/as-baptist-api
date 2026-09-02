"""FastAPI application entry point."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import Settings, get_settings
from app.core.errors import (
    ApiProblem,
    api_problem_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.core.logging import bind_request, clear_request, configure_logging
from app.core.security import TokenVerifier
from app.db.session import DatabaseRuntime
from app.routers.health import router as health_router


def _request_id(value: str | None) -> str:
    if value and len(value) <= 128 and all(char.isalnum() or char in "-_" for char in value):
        return value
    return uuid4().hex


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application and validate configuration before serving traffic."""

    active_settings = settings or get_settings()
    logger = configure_logging(active_settings.log_level)
    database = DatabaseRuntime(active_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(title=active_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = active_settings
    app.state.logger = logger
    app.state.token_verifier = TokenVerifier(active_settings)
    app.state.database = database
    app.state.readiness_probe = database.check_ready

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        bind_request(request_id)
        try:
            response = await call_next(request)
        finally:
            clear_request()
        response.headers["X-Request-ID"] = request_id
        return response

    app.add_exception_handler(ApiProblem, api_problem_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(health_router)
    return app


app = create_app()
