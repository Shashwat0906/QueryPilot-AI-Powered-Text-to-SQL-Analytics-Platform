"""Persist and read the request log (one row per /api/query call)."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from pathlib import Path

from sqlalchemy import Engine, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import NotFoundError
from app.models.request_log import Base, RequestLog

logger = logging.getLogger(__name__)

# Columns added after the first release. create_all() never alters an existing
# table, so they are added here (a tiny migration; Alembic would be the next
# step if the schema keeps growing).
_ADDED_COLUMNS = {"client_id": "VARCHAR(64)"}


def create_metadata_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


class HistoryService:
    def __init__(self, engine: Engine):
        self.engine = engine
        Base.metadata.create_all(engine)
        self._migrate()
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def _migrate(self) -> None:
        existing = {c["name"] for c in inspect(self.engine).get_columns(RequestLog.__tablename__)}
        with self.engine.begin() as conn:
            for name, sql_type in _ADDED_COLUMNS.items():
                if name not in existing:
                    logger.info("Adding column request_logs.%s", name)
                    conn.execute(text(f"ALTER TABLE request_logs ADD COLUMN {name} {sql_type}"))

    def record(self, log: RequestLog) -> None:
        with self._sessions.begin() as session:
            session.add(log)

    def list(self, *, limit: int = 50, offset: int = 0, status: str | None = None,
             search: str | None = None, client_id: str | None = None,
             ) -> tuple[list[RequestLog], int]:
        query = select(RequestLog)
        if client_id is not None:
            query = query.where(RequestLog.client_id == client_id)
        if status:
            query = query.where(RequestLog.status == status)
        if search:
            query = query.where(RequestLog.question.ilike(f"%{search}%"))
        with Session(self.engine) as session:
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.scalars(
                query.order_by(RequestLog.created_at.desc()).limit(limit).offset(offset)
            ).all()
        return list(rows), total

    def get(self, request_id: str, client_id: str | None = None) -> RequestLog:
        with Session(self.engine) as session:
            row = session.get(RequestLog, request_id)
        # Someone else's request looks exactly like a missing one.
        if row is None or (client_id is not None and row.client_id != client_id):
            raise NotFoundError(f"No request with id {request_id}.")
        return row

    def usage_today(self) -> tuple[int, float]:
        """(requests that called a real LLM, their estimated cost) since 00:00 UTC."""
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        with Session(self.engine) as session:
            count, cost = session.execute(
                select(func.count(), func.coalesce(func.sum(RequestLog.estimated_cost_usd), 0.0))
                .where(RequestLog.created_at >= start, RequestLog.llm_calls > 0,
                       RequestLog.provider != "mock")
            ).one()
        return int(count), float(cost)

    def all(self) -> list[RequestLog]:
        with Session(self.engine) as session:
            return list(session.scalars(select(RequestLog).order_by(RequestLog.created_at)).all())

    def clear(self) -> None:
        with self._sessions.begin() as session:
            session.query(RequestLog).delete()
