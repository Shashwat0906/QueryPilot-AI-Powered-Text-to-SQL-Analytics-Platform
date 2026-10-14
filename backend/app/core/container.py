"""Builds every service once at startup and wires them together.

Keeping construction in one place makes dependencies explicit and lets tests
swap pieces (e.g. a scripted fake LLM) by passing them into `build_container`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.db.database import create_readonly_engine, database_identity
from app.services.answer_service import AnswerService
from app.services.cache_service import QueryCache
from app.services.history_service import HistoryService, create_metadata_engine
from app.services.llm_service import LLMProvider, build_provider
from app.services.query_executor import QueryExecutor
from app.services.query_service import QueryService
from app.services.retry_service import RetryService
from app.services.schema_service import SchemaService
from app.services.sql_generator import SQLGenerator

logger = logging.getLogger("querypilot")


@dataclass
class Container:
    settings: Settings
    business_engine: Engine
    provider: LLMProvider
    schema_service: SchemaService
    cache: QueryCache
    history: HistoryService
    query_service: QueryService
    rate_limiter: RateLimiter
    started_at: float
    history_persistent: bool = True


def _build_history(url: str) -> tuple[HistoryService, bool]:
    """Connect to the history DB; if it's unreachable, keep serving with a
    temporary in-memory history instead of crashing (e.g. an expired free
    Postgres). /api/health reports this as degraded."""
    try:
        return HistoryService(create_metadata_engine(url)), True
    except SQLAlchemyError:
        logger.exception("History database unreachable - using TEMPORARY in-memory history")
        engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        return HistoryService(engine), False


def build_container(settings: Settings, provider: LLMProvider | None = None) -> Container:
    engine = create_readonly_engine(settings.database_url)
    provider = provider or build_provider(settings)
    schema_service = SchemaService(engine, settings.approved_tables, settings.schema_sample_values)
    cache = QueryCache(
        enabled=settings.cache_enabled, ttl_seconds=settings.cache_ttl_seconds,
        max_entries=settings.cache_max_entries, sensitive_columns=settings.cache_sensitive_columns,
    )
    # When the schema structure changes, drop cache entries built for the old one.
    schema_service.on_change(cache.invalidate_schema)

    executor = QueryExecutor(engine, settings.approved_tables)
    retry = RetryService(
        SQLGenerator(provider, executor.dialect), executor,
        max_corrections=settings.max_correction_attempts,
        max_rows=settings.max_result_rows,
        timeout_seconds=settings.query_timeout_seconds,
    )
    history, history_persistent = _build_history(settings.metadata_database_url)
    query_service = QueryService(
        settings=settings, provider=provider, schema_service=schema_service, retry_service=retry,
        answer_service=AnswerService(provider, settings.answer_mode, settings.answer_preview_rows),
        cache=cache, history=history, database_id=database_identity(settings.database_url),
    )
    return Container(
        settings=settings, business_engine=engine, provider=provider,
        schema_service=schema_service, cache=cache, history=history,
        query_service=query_service, rate_limiter=RateLimiter(settings.rate_limit_per_minute),
        started_at=time.monotonic(),
        history_persistent=history_persistent,
    )
