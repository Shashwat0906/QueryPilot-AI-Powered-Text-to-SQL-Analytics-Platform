"""Executes *already validated* SQL against the business database.

Runtime safety layers (in addition to `sql_validator`):

* Read-only connection (`mode=ro` + `PRAGMA query_only`), see `app/db/database.py`.
* SQLite **authorizer**: SQLite calls `_authorizer` for every operation while
  compiling a statement. We allow only SELECT, reading approved tables, a
  fixed list of harmless functions and recursive CTEs. Anything else (writes,
  PRAGMA, ATTACH, load_extension, reading sqlite_master ...) is denied by
  SQLite itself - even if the parser-based validator somehow missed it.
* **Timeout**: a progress handler runs every 10k SQLite VM instructions and
  aborts the query once the deadline passes.
* **Row cap**: we fetch at most `max_rows + 1` rows, so a huge result cannot
  exhaust memory; the extra row only tells us the result was truncated.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine

from app.core.errors import ErrorCategory, QueryExecutionError

# Functions a read-only analytical query may call. Everything else is denied.
SAFE_FUNCTIONS = {
    # aggregates
    "count", "sum", "total", "avg", "min", "max", "group_concat", "string_agg",
    # window functions
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag",
    "lead", "first_value", "last_value", "nth_value",
    # scalar
    "abs", "round", "coalesce", "ifnull", "nullif", "iif", "length", "lower", "upper",
    "trim", "ltrim", "rtrim", "substr", "substring", "replace", "instr", "printf", "format",
    "typeof", "cast", "like", "glob", "char", "hex", "quote", "unicode", "sign",
    "ceil", "ceiling", "floor", "trunc", "power", "pow", "sqrt", "exp", "ln", "log",
    "log10", "log2", "mod", "pi", "concat", "concat_ws",
    # date / time
    "date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T]\d{2}:\d{2}(:\d{2})?)?$")


@dataclass
class ColumnInfo:
    name: str
    type: str  # "number" | "date" | "string" | "boolean" | "null"


@dataclass
class ExecutionResult:
    columns: list[ColumnInfo]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: float


def _make_authorizer(readable: set[str]):
    def authorizer(action, arg1, arg2, db_name, trigger):  # noqa: ARG001 - SQLite signature
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # arg1 = table name (approved table, or a CTE defined by the query).
            if arg1 is None or arg1.lower() in readable:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            # arg2 = function name
            return sqlite3.SQLITE_OK if (arg2 or "").lower() in SAFE_FUNCTIONS else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return authorizer


def _sanitize(message: str) -> str:
    """Keep only the short SQLite message; drop anything path-like."""
    message = message.splitlines()[0] if message else "Database error"
    message = re.sub(r"(/[\w.\-]+)+", "<path>", message)
    return message[:200]


def classify_sqlite_error(exc: sqlite3.Error) -> QueryExecutionError:
    msg = _sanitize(str(exc))
    lowered = msg.lower()
    if "interrupted" in lowered:
        return QueryExecutionError(
            "The query took too long and was stopped.",
            category=ErrorCategory.RESOURCE,
            code="query_timeout",
        )
    if "not authorized" in lowered or "prohibited" in lowered or "readonly" in lowered:
        return QueryExecutionError(
            "The query tried an operation that is not permitted.",
            category=ErrorCategory.SECURITY,
            code="operation_not_permitted",
        )
    # no such column/table, syntax error, ambiguous column, misuse of aggregate,
    # wrong number of arguments ... -> the LLM can usually fix these.
    return QueryExecutionError(msg, category=ErrorCategory.RECOVERABLE, code="sql_runtime_error")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


def _infer_type(values: list[Any]) -> str:
    sample = [v for v in values if v is not None][:50]
    if not sample:
        return "null"
    if all(isinstance(v, bool) for v in sample):
        return "boolean"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in sample):
        return "number"
    if all(isinstance(v, str) and _DATE_RE.match(v) for v in sample):
        return "date"
    return "string"


class QueryExecutor:
    def __init__(self, engine: Engine, approved_tables: list[str]):
        self._engine = engine
        self._approved = {t.lower() for t in approved_tables}

    @property
    def dialect(self) -> str:
        return self._engine.dialect.name

    def execute(
        self,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: float,
        cte_names: frozenset[str] = frozenset(),
    ) -> ExecutionResult:
        if self.dialect != "sqlite":  # pragma: no cover - Postgres path is planned/untested
            return self._execute_generic(sql, max_rows=max_rows, timeout_seconds=timeout_seconds)

        started = time.perf_counter()
        deadline = started + timeout_seconds
        with self._engine.connect() as conn:
            raw: sqlite3.Connection = conn.connection.dbapi_connection  # type: ignore[assignment]
            raw.set_authorizer(_make_authorizer(self._approved | {c.lower() for c in cte_names}))
            raw.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 10_000)
            try:
                cursor = raw.execute(sql)
                fetched = cursor.fetchmany(max_rows + 1)
                names = [d[0] for d in cursor.description or []]
            except sqlite3.Error as exc:
                raise classify_sqlite_error(exc) from None
            finally:
                # Pooled connection: remove our hooks before giving it back.
                raw.set_authorizer(None)
                raw.set_progress_handler(None, 0)
        duration_ms = (time.perf_counter() - started) * 1000
        return self._build_result(names, fetched, max_rows, duration_ms)

    def _execute_generic(self, sql: str, *, max_rows: int, timeout_seconds: float) -> ExecutionResult:
        """Planned PostgreSQL path: read-only transaction + statement_timeout."""
        from sqlalchemy import text

        started = time.perf_counter()
        with self._engine.connect() as conn:
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_seconds * 1000)}")
            result = conn.execute(text(sql))
            fetched = result.fetchmany(max_rows + 1)
            names = list(result.keys())
        return self._build_result(names, fetched, max_rows, (time.perf_counter() - started) * 1000)

    @staticmethod
    def _build_result(names, fetched, max_rows: int, duration_ms: float) -> ExecutionResult:
        truncated = len(fetched) > max_rows
        rows = [[_json_value(v) for v in row] for row in fetched[:max_rows]]
        columns = [
            ColumnInfo(name=name, type=_infer_type([r[i] for r in rows]))
            for i, name in enumerate(names)
        ]
        return ExecutionResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=round(duration_ms, 2),
        )
