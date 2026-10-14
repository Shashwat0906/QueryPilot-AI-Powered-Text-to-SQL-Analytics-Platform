import pytest

from app.core.errors import ErrorCategory, QueryExecutionError
from app.services.query_executor import QueryExecutor
from tests.conftest import APPROVED


@pytest.fixture
def executor(engine):
    return QueryExecutor(engine, APPROVED)


def test_returns_columns_types_and_rows(executor):
    result = executor.execute(
        "SELECT order_id, order_date, status, shipping_fee FROM orders ORDER BY order_id LIMIT 3",
        max_rows=10, timeout_seconds=5,
    )
    assert [c.name for c in result.columns] == ["order_id", "order_date", "status", "shipping_fee"]
    assert [c.type for c in result.columns] == ["number", "date", "string", "number"]
    assert result.row_count == 3
    assert result.truncated is False
    assert result.duration_ms >= 0


def test_row_limit_truncates(executor):
    result = executor.execute("SELECT order_id FROM orders", max_rows=25, timeout_seconds=5)
    assert result.row_count == 25
    assert result.truncated is True


def test_empty_result(executor):
    result = executor.execute("SELECT order_id FROM orders WHERE 1 = 0", max_rows=5, timeout_seconds=5)
    assert result.row_count == 0 and result.rows == []


def test_timeout_stops_runaway_query(executor):
    sql = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
    with pytest.raises(QueryExecutionError) as exc:
        executor.execute(sql, max_rows=5, timeout_seconds=0.2, cte_names=frozenset({"c"}))
    assert exc.value.code == "query_timeout"
    assert exc.value.category == ErrorCategory.RESOURCE


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sqlite_master",           # internal table
        "SELECT load_extension('x')",            # dangerous function
        "PRAGMA table_info(orders)",             # pragma
        "DELETE FROM orders",                    # write
        "CREATE TABLE t (x INT)",                # DDL
    ],
)
def test_runtime_guards_block_unsafe_sql_even_without_validator(executor, sql):
    """Defence in depth: the SQLite authorizer + read-only connection alone stop these."""
    with pytest.raises(QueryExecutionError) as exc:
        executor.execute(sql, max_rows=5, timeout_seconds=5)
    assert exc.value.category == ErrorCategory.SECURITY


def test_database_error_is_recoverable_and_sanitized(executor):
    with pytest.raises(QueryExecutionError) as exc:
        executor.execute("SELECT SUM(SUM(quantity)) AS x FROM order_items", max_rows=5, timeout_seconds=5)
    assert exc.value.category == ErrorCategory.RECOVERABLE
    assert "aggregate" in exc.value.message
    assert "/" not in exc.value.message  # no file paths


def test_connection_is_read_only_at_sqlite_level(engine):
    with engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        assert raw.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(Exception, match="readonly|read-only|attempt to write"):
            raw.execute("INSERT INTO customers (customer_id) VALUES (99999)")
