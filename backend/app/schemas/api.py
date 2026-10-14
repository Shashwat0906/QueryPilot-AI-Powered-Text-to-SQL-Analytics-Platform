"""Pydantic request/response models - the public API contract.

FastAPI uses these to validate input, serialise output and generate the
OpenAPI (Swagger) docs at /docs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

QueryStatus = Literal["success", "failed", "rejected", "unanswerable"]


# ---------- errors ----------
class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------- query ----------
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500,
                          examples=["Show the top five products by revenue."])
    use_cache: bool = Field(True, description="Set false to bypass the result cache.")

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("Question is too short.")
        return value


class ColumnOut(BaseModel):
    name: str
    type: str


class AttemptOut(BaseModel):
    number: int
    kind: str
    sql: str | None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    error_category: str | None = None
    llm_latency_ms: float | None = None
    db_latency_ms: float | None = None


class Timings(BaseModel):
    generation_ms: float = Field(description="Sum of SQL generation + correction LLM calls")
    db_ms: float = Field(description="Database execution time of the attempts")
    answer_ms: float = Field(description="Answer-summary LLM call")
    total_ms: float = Field(description="Wall-clock time for the whole request")


class Usage(BaseModel):
    llm_calls: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    cost_status: Literal["estimated", "unavailable", "no_llm_calls"]
    cost_note: str


class CacheInfo(BaseModel):
    hit: bool
    stored: bool = False
    reason: str | None = None


class PipelineErrorOut(BaseModel):
    code: str
    message: str
    category: str


class QueryResponse(BaseModel):
    request_id: str
    created_at: datetime
    question: str
    status: QueryStatus
    answer: str | None = None
    sql: str | None = None
    explanation: str | None = None
    tables_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    columns: list[ColumnOut] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    max_rows: int
    attempts: list[AttemptOut] = Field(default_factory=list)
    retry_count: int = 0
    timings: Timings
    usage: Usage
    cache: CacheInfo
    provider: str
    model: str
    is_mock_provider: bool
    warnings: list[str] = Field(
        default_factory=list,
        description="Things the user should know about a successful result (e.g. row limit hit).",
    )
    error: PipelineErrorOut | None = None


# ---------- schema ----------
class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    note: str | None = None
    sample_values: list[str] | None = None


class ForeignKeySchema(BaseModel):
    column: str
    references_table: str
    references_column: str


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnSchema]
    primary_key: list[str]
    foreign_keys: list[ForeignKeySchema]
    row_count: int
    note: str | None = None


class RelationshipSchema(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str


class SchemaResponse(BaseModel):
    version: str
    database_type: str
    data_reference_date: str | None
    business_rules: list[str]
    tables: list[TableSchema]
    relationships: list[RelationshipSchema]


# ---------- history ----------
class HistoryItem(BaseModel):
    request_id: str
    created_at: datetime
    question: str
    status: str
    final_sql: str | None
    row_count: int | None
    retry_count: int
    total_ms: float
    cache_hit: bool
    estimated_cost_usd: float | None
    cost_status: str
    error_code: str | None

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite stores datetimes without a timezone; we always write UTC.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class HistoryDetail(HistoryItem):
    error_message: str | None
    error_category: str | None
    explanation: str | None
    answer: str | None
    attempts: list[AttemptOut]
    tables_used: list[str]
    assumptions: list[str]
    llm_calls: int
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    generation_ms: float
    db_ms: float


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int
    limit: int
    offset: int


# ---------- config / health / cache ----------
class CacheStats(BaseModel):
    enabled: bool
    entries: int
    max_entries: int
    ttl_seconds: int
    hits: int
    misses: int
    hit_rate: float | None
    skipped_sensitive: int


class ConfigResponse(BaseModel):
    app_name: str
    version: str
    environment: str
    database_type: str
    database_name: str
    approved_tables: list[str]
    llm_provider: str
    llm_model: str
    is_mock_provider: bool
    llm_api_key_configured: bool
    answer_mode: str
    max_result_rows: int
    query_timeout_seconds: float
    max_correction_attempts: int
    max_question_length: int
    rate_limit_per_minute: int
    daily_llm_request_limit: int = Field(description="0 = no daily cap")
    daily_cost_limit_usd: float = Field(description="0 = no daily cap")
    history_scope: Literal["all", "client"]
    cache: CacheStats
    model_pricing_usd_per_mtok: dict[str, float] | None
    settings_editable: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "error"]
    database_detail: str | None = None
    schema_version: str | None = None
    llm_provider: str
    llm_configured: bool
    history_storage: Literal["persistent", "temporary"]
    uptime_seconds: float


class CacheClearResponse(BaseModel):
    cleared_entries: int
