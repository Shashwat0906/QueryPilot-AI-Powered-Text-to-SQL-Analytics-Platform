"""The /api/query use case, end to end.

    1. request id + timer
    2. schema (cached in SchemaService)
    3. cache lookup (key includes schema version, provider, model, row limit)
    3b. daily spend caps (only when a real LLM would be called)
    4. RetryService: generate -> validate -> execute -> (correct)*
    5. AnswerService: grounded natural-language answer
    6. cost + latency summary
    7. cache store (success only, non-sensitive only)
    8. history record (always, success or failure)
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from app.core.config import Settings
from app.core.errors import RateLimitError
from app.models.request_log import RequestLog
from app.schemas.api import (
    AttemptOut,
    CacheInfo,
    ColumnOut,
    PipelineErrorOut,
    QueryResponse,
    Timings,
    Usage,
)
from app.services.answer_service import AnswerService
from app.services.cache_service import QueryCache
from app.services.cost_tracker import summarize_cost
from app.services.history_service import HistoryService
from app.services.llm_service import LLMProvider
from app.services.retry_service import RetryService
from app.services.schema_service import SchemaService
from app.services.sql_generator import PROMPT_VERSION

logger = logging.getLogger("querypilot.query")


class QueryService:
    def __init__(self, *, settings: Settings, provider: LLMProvider, schema_service: SchemaService,
                 retry_service: RetryService, answer_service: AnswerService, cache: QueryCache,
                 history: HistoryService, database_id: str):
        self.settings = settings
        self.provider = provider
        self.schema_service = schema_service
        self.retry_service = retry_service
        self.answer_service = answer_service
        self.cache = cache
        self.history = history
        self.database_id = database_id

    def run(self, question: str, *, request_id: str | None = None, use_cache: bool = True,
            scope: str = "anonymous", client_id: str | None = None) -> QueryResponse:
        request_id = request_id or str(uuid.uuid4())
        started = time.perf_counter()
        created_at = datetime.now(timezone.utc)
        schema = self.schema_service.get_schema()

        cache_key = QueryCache.make_key(
            question=question, database_id=self.database_id, schema_version=schema.version,
            provider=self.provider.name, model=self.provider.model,
            max_rows=self.settings.max_result_rows, scope=scope, prompt_version=PROMPT_VERSION,
            answer_mode=self.answer_service.mode,
        )

        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                response = self._from_cache(cached, request_id, created_at, question, started)
                self._record(response, client_id)
                return response

        self._enforce_daily_limits()
        pipeline = self.retry_service.run(question, schema)

        answer, answer_ms, answer_call = None, 0.0, None
        if pipeline.status == "success" and pipeline.execution and pipeline.validated:
            t0 = time.perf_counter()
            answer, answer_call = self.answer_service.answer(
                question, pipeline.validated.sql, pipeline.execution
            )
            answer_ms = (time.perf_counter() - t0) * 1000

        calls = list(pipeline.llm_calls) + ([answer_call] if answer_call else [])
        cost = summarize_cost(calls, self.provider.model, self.settings.model_pricing)
        execution = pipeline.execution
        generated = pipeline.generated

        response = QueryResponse(
            request_id=request_id,
            created_at=created_at,
            question=question,
            status=pipeline.status,  # type: ignore[arg-type]
            answer=answer,
            sql=pipeline.validated.sql if pipeline.validated else None,
            explanation=generated.explanation if generated else None,
            tables_used=pipeline.validated.tables if pipeline.validated else
            (generated.tables_used if generated else []),
            assumptions=generated.assumptions if generated else [],
            columns=[ColumnOut(name=c.name, type=c.type) for c in execution.columns] if execution else [],
            rows=execution.rows if execution else [],
            row_count=execution.row_count if execution else 0,
            truncated=execution.truncated if execution else False,
            max_rows=self.settings.max_result_rows,
            attempts=[AttemptOut(**vars(a)) for a in pipeline.attempts],
            retry_count=pipeline.retry_count,
            timings=Timings(
                generation_ms=pipeline.generation_ms,
                db_ms=pipeline.db_ms,
                answer_ms=round(answer_ms, 2),
                total_ms=round((time.perf_counter() - started) * 1000, 2),
            ),
            usage=Usage(
                llm_calls=cost.llm_calls, input_tokens=cost.input_tokens,
                output_tokens=cost.output_tokens, estimated_cost_usd=cost.estimated_cost_usd,
                cost_status=cost.status,  # type: ignore[arg-type]
                cost_note=cost.note,
            ),
            cache=CacheInfo(hit=False, reason=None if use_cache else "bypassed by request"),
            provider=self.provider.name,
            model=self.provider.model,
            is_mock_provider=not self.provider.is_real_llm,
            warnings=self._warnings(pipeline.warnings, execution),
            error=PipelineErrorOut(**vars(pipeline.error)) if pipeline.error else None,
        )

        if use_cache and response.status == "success":
            stored = self.cache.set(
                cache_key, response.model_dump(mode="json"), schema_version=schema.version,
                column_names=[c.name for c in response.columns],
            )
            response.cache.stored = stored
            if not stored:
                response.cache.reason = ("cache disabled" if not self.cache.enabled
                                         else "result contains sensitive columns")

        self._record(response, client_id)
        logger.info(
            "query request_id=%s status=%s retries=%d rows=%d total_ms=%.1f cost=%s",
            request_id, response.status, response.retry_count, response.row_count,
            response.timings.total_ms, response.usage.estimated_cost_usd,
        )
        return response

    def _warnings(self, pipeline_warnings: list[str], execution) -> list[str]:
        warnings = list(pipeline_warnings)
        if execution is not None and execution.truncated:
            warnings.append(
                f"Only the first {self.settings.max_result_rows:,} rows are shown (row limit). "
                "Ask for an aggregate or a narrower filter to see everything."
            )
        return warnings

    def _from_cache(self, cached: dict, request_id: str, created_at: datetime, question: str,
                    started: float) -> QueryResponse:
        response = QueryResponse.model_validate(cached)
        response.request_id = request_id
        response.created_at = created_at
        response.question = question
        response.retry_count = 0  # no retries happened in *this* request
        response.timings = Timings(generation_ms=0, db_ms=0, answer_ms=0,
                                   total_ms=round((time.perf_counter() - started) * 1000, 2))
        response.usage = Usage(llm_calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
                               cost_status="no_llm_calls",
                               cost_note="Served from cache - no LLM calls were made.")
        response.cache = CacheInfo(hit=True, stored=False, reason="served from cache")
        return response

    def _enforce_daily_limits(self) -> None:
        """Stop a public demo from running up an unbounded LLM bill."""
        request_cap = self.settings.daily_llm_request_limit
        cost_cap = self.settings.daily_cost_limit_usd
        if not self.provider.is_real_llm or (request_cap <= 0 and cost_cap <= 0):
            return
        try:
            count, cost = self.history.usage_today()
        except Exception:  # can't count usage -> don't risk unbounded spend
            logger.exception("Could not read today's usage; refusing new LLM calls")
            raise RateLimitError(
                "New questions are temporarily unavailable. Please try again later.",
                code="usage_unavailable",
            ) from None
        if (request_cap > 0 and count >= request_cap) or (cost_cap > 0 and cost >= cost_cap):
            raise RateLimitError(
                "The daily question limit for this demo has been reached. Example questions "
                "that were already asked today still work (they come from the cache); "
                "new questions are available again after 00:00 UTC.",
                code="daily_limit_reached",
            )

    def _record(self, response: QueryResponse, client_id: str | None = None) -> None:
        try:
            self.history.record(
                RequestLog(
                    request_id=response.request_id,
                    created_at=response.created_at,
                    question=response.question,
                    status=response.status,
                    error_code=response.error.code if response.error else None,
                    error_message=response.error.message if response.error else None,
                    error_category=response.error.category if response.error else None,
                    final_sql=response.sql or next(
                        (a.sql for a in reversed(response.attempts) if a.sql), None),
                    explanation=response.explanation,
                    answer=response.answer,
                    attempts=[a.model_dump() for a in response.attempts],
                    tables_used=response.tables_used,
                    assumptions=response.assumptions,
                    row_count=response.row_count if response.status == "success" else None,
                    retry_count=response.retry_count,
                    llm_calls=response.usage.llm_calls,
                    provider=response.provider,
                    model=response.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    estimated_cost_usd=response.usage.estimated_cost_usd,
                    cost_status=response.usage.cost_status,
                    generation_ms=response.timings.generation_ms,
                    db_ms=response.timings.db_ms,
                    total_ms=response.timings.total_ms,
                    cache_hit=response.cache.hit,
                    client_id=client_id,
                )
            )
        except Exception:  # history must never break the user's request
            logger.exception("Failed to record request %s", response.request_id)
