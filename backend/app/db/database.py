"""Connection layer for the *business* database (the one users ask about).

Design goals:
* Every connection QueryPilot opens to the business database is read-only.
* SQLAlchemy is the only place that knows the database URL, so adding
  PostgreSQL later means adding a branch here and in `query_executor`, not
  rewriting the services.

SQLite read-only defence in depth (each layer would stop a write on its own):
1. The file is opened with the URI `file:...?mode=ro`, so the OS-level handle
   cannot write.
2. `PRAGMA query_only = ON` makes SQLite refuse any statement that writes.
3. An *authorizer* callback (installed by `query_executor`) rejects every
   action other than SELECT / READ of approved tables / safe functions.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def sqlite_path_from_url(url: str) -> Path:
    database = make_url(url).database
    if not database:
        raise ValueError("SQLite URL must point to a file")
    return Path(database)


def _readonly_sqlite_engine(url: str) -> Engine:
    path = sqlite_path_from_url(url)

    def connect() -> sqlite3.Connection:
        if not path.exists():
            raise FileNotFoundError(
                f"Business database not found at {path}. Run `python -m scripts.seed_database`."
            )
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
        return conn

    return create_engine("sqlite://", creator=connect, pool_pre_ping=False)


def _readonly_postgres_engine(url: str) -> Engine:
    # Planned / untested: PostgreSQL support. Read-only is enforced per
    # transaction by the executor (SET TRANSACTION READ ONLY). In production
    # you would ALSO connect as a database role that only has SELECT grants.
    engine = create_engine(url, pool_pre_ping=True)

    @event.listens_for(engine, "begin")
    def _readonly(conn):  # pragma: no cover - requires a Postgres server
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")

    return engine


def create_readonly_engine(url: str) -> Engine:
    dialect = make_url(url).get_backend_name()
    if dialect == "sqlite":
        return _readonly_sqlite_engine(url)
    if dialect == "postgresql":
        return _readonly_postgres_engine(url)
    raise ValueError(f"Unsupported database dialect: {dialect}")


@lru_cache
def get_business_engine() -> Engine:
    return create_readonly_engine(get_settings().database_url)


def database_identity(url: str) -> str:
    """Stable identifier for the database, used in cache keys.

    Never includes the password: `render_as_string(hide_password=True)`.
    """

    return make_url(url).render_as_string(hide_password=True)
