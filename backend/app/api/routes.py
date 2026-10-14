"""HTTP routes. Deliberately thin: parse input, call a service, return a model."""

from __future__ import annotations

import hashlib
import re
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app import __version__
from app.core.container import Container
from app.core.errors import BadRequestError, RateLimitError
from app.schemas.api import (
    CacheClearResponse,
    ConfigResponse,
    ErrorResponse,
    HealthResponse,
    HistoryDetail,
    HistoryItem,
    HistoryResponse,
    QueryRequest,
    QueryResponse,
    SchemaResponse,
)
from app.services.analytics_service import compute_analytics

router = APIRouter(prefix="/api")

ERRORS = {
    400: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
    429: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
}


def get_container(request: Request) -> Container:
    return request.app.state.container


def client_ip(request: Request, header: str) -> str:
    """Client address for rate limiting.

    With no trusted proxy header configured, use the TCP peer. Otherwise take
    the LAST address in the header: proxies append to the right, so anything
    further left may have been supplied by the client itself.
    """
    if header:
        value = request.headers.get(header, "")
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


_CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{16,64}$")


def hashed_client_id(request: Request) -> str | None:
    """Anonymous per-browser ID from X-Client-ID, stored only as a hash."""
    raw = request.headers.get("X-Client-ID", "")
    if not _CLIENT_ID.match(raw):
        return None
    return hashlib.sha256(raw.encode()).hexdigest()


def history_owner(request: Request, c: Container) -> str | None:
    """The client filter for history reads, or None when history is shared."""
    if c.settings.history_scope != "client":
        return None
    # A browser without an ID sees nothing rather than everyone's history.
    return hashed_client_id(request) or "no-client-id"


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(c: Container = Depends(get_container)) -> HealthResponse:
    db_ok, detail, version = True, None, None
    try:
        with c.business_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        version = c.schema_service.get_schema().version
    except Exception:  # noqa: BLE001 - report, don't leak
        db_ok, detail = False, "Business database is unreachable. Run the seed script."
    return HealthResponse(
        status="ok" if db_ok and c.history_persistent else "degraded",
        version=__version__,
        database="ok" if db_ok else "error",
        database_detail=detail,
        schema_version=version,
        llm_provider=c.provider.name,
        llm_configured=c.provider.is_real_llm,
        history_storage="persistent" if c.history_persistent else "temporary",
        uptime_seconds=round(time.monotonic() - c.started_at, 1),
    )


@router.get("/schema", response_model=SchemaResponse, tags=["schema"], responses=ERRORS)
def get_schema(refresh: bool = False, c: Container = Depends(get_container)) -> SchemaResponse:
    schema = c.schema_service.refresh() if refresh else c.schema_service.get_schema()
    return SchemaResponse(database_type=c.settings.database_type, **schema.to_dict())


@router.post("/query", response_model=QueryResponse, tags=["query"], responses=ERRORS)
async def run_query(body: QueryRequest, request: Request,
                    c: Container = Depends(get_container)) -> QueryResponse:
    """Generate SQL with the LLM, validate it, run it read-only, and answer.

    Pipeline outcomes (success / failed / rejected / unanswerable) are returned
    with HTTP 200 and a `status` field, because the response carries useful
    detail (attempts, SQL, cost) in every case. HTTP errors are reserved for
    problems with the request itself (validation, rate limit, server error).
    """
    if len(body.question) > c.settings.max_question_length:
        raise BadRequestError(
            f"Question is too long (max {c.settings.max_question_length} characters).",
            code="question_too_long",
        )
    allowed, retry_after = c.rate_limiter.allow(client_ip(request, c.settings.client_ip_header))
    if not allowed:
        raise RateLimitError(
            f"Too many requests. Try again in {retry_after:.0f}s.",
            details={"retry_after_seconds": retry_after},
        )
    # The pipeline is blocking (HTTP + SQLite); run it off the event loop.
    return await run_in_threadpool(
        c.query_service.run, body.question,
        request_id=request.state.request_id, use_cache=body.use_cache,
        client_id=hashed_client_id(request),
    )


@router.get("/history", response_model=HistoryResponse, tags=["history"])
def history(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern="^(success|failed|rejected|unanswerable)$"),
    search: str | None = Query(None, max_length=200),
    c: Container = Depends(get_container),
) -> HistoryResponse:
    rows, total = c.history.list(limit=limit, offset=offset, status=status, search=search,
                                 client_id=history_owner(request, c))
    return HistoryResponse(
        items=[HistoryItem.model_validate(r, from_attributes=True) for r in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get("/history/{request_id}", response_model=HistoryDetail, tags=["history"],
            responses={404: {"model": ErrorResponse}})
def history_detail(request_id: str, request: Request,
                   c: Container = Depends(get_container)) -> HistoryDetail:
    row = c.history.get(request_id, client_id=history_owner(request, c))
    return HistoryDetail.model_validate(row, from_attributes=True)


@router.get("/analytics", tags=["analytics"])
def analytics(c: Container = Depends(get_container)) -> dict:
    data = compute_analytics(c.history.all())
    data["cache"] = c.cache.stats()
    return data


@router.get("/config", response_model=ConfigResponse, tags=["system"])
def config(c: Container = Depends(get_container)) -> ConfigResponse:
    s = c.settings
    price = s.model_pricing.get(c.provider.model)
    return ConfigResponse(
        app_name=s.app_name,
        version=__version__,
        environment=s.environment,
        database_type=s.database_type,
        # Only the file name / db name - never the full URL (could hold a password).
        database_name=(make_url(s.database_url).database or "").rsplit("/", 1)[-1],
        approved_tables=[t.name for t in c.schema_service.get_schema().tables],
        llm_provider=c.provider.name,
        llm_model=c.provider.model,
        is_mock_provider=not c.provider.is_real_llm,
        llm_api_key_configured=c.provider.is_real_llm,
        answer_mode=s.answer_mode if c.provider.is_real_llm else "template",
        max_result_rows=s.max_result_rows,
        query_timeout_seconds=s.query_timeout_seconds,
        max_correction_attempts=s.max_correction_attempts,
        max_question_length=s.max_question_length,
        rate_limit_per_minute=s.rate_limit_per_minute,
        daily_llm_request_limit=s.daily_llm_request_limit,
        daily_cost_limit_usd=s.daily_cost_limit_usd,
        history_scope=s.history_scope,
        cache=c.cache.stats(),
        model_pricing_usd_per_mtok=price,
    )


@router.post("/cache/clear", response_model=CacheClearResponse, tags=["system"])
def clear_cache(c: Container = Depends(get_container)) -> CacheClearResponse:
    return CacheClearResponse(cleared_entries=c.cache.clear())
