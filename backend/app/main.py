"""FastAPI application factory.

Run locally:   uvicorn app.main:app --reload --port 8000
Swagger docs:  http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.container import build_container
from app.core.errors import AppError
from app.services.llm_service import LLMProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("querypilot")


def _error(status: int, code: str, message: str, request: Request, details: dict | None = None):
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id,
                           "details": details or {}}},
        headers={"X-Request-ID": request_id} if request_id else None,
    )


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = settings.enable_api_docs
    app = FastAPI(
        title="QueryPilot API",
        version=__version__,
        description="AI-powered text-to-SQL analytics: ask questions in plain English, "
                    "get validated, read-only SQL and real results.",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.container = build_container(settings, provider)
    logger.info(
        "QueryPilot %s starting: environment=%s provider=%s history=%s",
        __version__, settings.environment, app.state.container.provider.name,
        settings.metadata_database_url.split(":", 1)[0],  # dialect only, never credentials
    )

    # Browsers may only call the API from these origins. (CORS does not stop
    # scripts or curl - the rate limit and daily caps do that.)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID", "X-Client-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        # Accept a well-formed client id (useful for tracing), otherwise make one.
        incoming = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(uuid.UUID(incoming))
        except ValueError:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, request, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return _error(422, "invalid_request", "The request body is invalid.", request,
                      {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, "http_error", str(exc.detail), request)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # Full traceback goes to the server log only.
        logger.exception("Unhandled error on %s", request.url.path)
        return _error(500, "internal_error", "An unexpected error occurred.", request)

    app.include_router(router)
    return app


app = create_app()
