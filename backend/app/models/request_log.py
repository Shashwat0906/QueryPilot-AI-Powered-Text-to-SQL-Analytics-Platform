"""ORM model for QueryPilot's own request log (history + analytics).

Stored in a separate, writable metadata database - never in the business
database, which the app only opens read-only. Result rows are deliberately
NOT stored (they may contain business data); history keeps SQL and metadata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    __tablename__ = "request_logs"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)  # success|failed|rejected|unanswerable
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_category: Mapped[str | None] = mapped_column(String(32))

    final_sql: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[list] = mapped_column(JSON, default=list)
    tables_used: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)

    row_count: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)

    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    cost_status: Mapped[str] = mapped_column(String(20))

    generation_ms: Mapped[float] = mapped_column(Float, default=0)
    db_ms: Mapped[float] = mapped_column(Float, default=0)
    total_ms: Mapped[float] = mapped_column(Float)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    # SHA-256 of the anonymous browser ID (never the raw ID). Used to show each
    # visitor only their own history on a public deployment.
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)
