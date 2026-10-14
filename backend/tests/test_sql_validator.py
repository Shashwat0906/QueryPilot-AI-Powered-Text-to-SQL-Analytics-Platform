import sqlite3

import pytest

from app.core.errors import ErrorCategory, SQLValidationError
from app.db.database import create_readonly_engine
from app.services.schema_service import inspect_schema
from app.services.sql_validator import validate_sql

REVENUE_TOP5 = """
SELECT p.name, ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue
FROM order_items oi
JOIN products p ON p.product_id = oi.product_id
JOIN orders o ON o.order_id = oi.order_id
WHERE o.status NOT IN ('cancelled', 'refunded')
GROUP BY p.product_id, p.name ORDER BY revenue DESC LIMIT 5
"""


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM customers",
        REVENUE_TOP5,
        "SELECT * FROM products;",  # a single trailing semicolon is fine
        "WITH monthly AS (SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS n "
        "FROM orders GROUP BY month) SELECT month, n FROM monthly ORDER BY month",
        "SELECT name FROM products p WHERE NOT EXISTS "
        "(SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id)",
        "SELECT city FROM customers UNION SELECT name FROM products",
        "SELECT c.segment, COUNT(*) AS n, RANK() OVER (ORDER BY COUNT(*) DESC) AS rnk "
        "FROM customers c GROUP BY c.segment",
        "SELECT x.n FROM (SELECT COUNT(*) AS n FROM orders) AS x",
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c LIMIT 5) SELECT x FROM c",
    ],
)
def test_valid_read_only_queries_pass(sql, schema):
    result = validate_sql(sql, schema)
    assert result.sql
    assert ";" not in result.sql


def test_validated_sql_is_canonical_and_lists_tables(schema):
    result = validate_sql(REVENUE_TOP5 + " -- trailing comment", schema)
    assert result.tables == ["order_items", "products", "orders"]
    assert "--" not in result.sql


def test_cte_names_are_reported(schema):
    result = validate_sql("WITH t AS (SELECT order_id FROM orders) SELECT order_id FROM t", schema)
    assert result.cte_names == frozenset({"t"})


@pytest.mark.parametrize(
    "sql, code",
    [
        ("DELETE FROM orders", "forbidden_statement"),
        ("UPDATE products SET unit_price = 0", "forbidden_statement"),
        ("INSERT INTO customers (customer_id) VALUES (999)", "forbidden_statement"),
        ("DROP TABLE orders", "forbidden_statement"),
        ("ALTER TABLE orders ADD COLUMN x INT", "forbidden_statement"),
        ("CREATE TABLE x (id INT)", "forbidden_statement"),
        ("TRUNCATE TABLE orders", "forbidden_statement"),
        ("REPLACE INTO products VALUES (1)", "forbidden_statement"),
        ("PRAGMA table_info(orders)", "forbidden_statement"),
        ("ATTACH DATABASE 'other.db' AS other", "forbidden_statement"),
        ("VACUUM", "forbidden_statement"),
        ("SELECT * INTO backup FROM orders", "forbidden_statement"),
        ("WITH x AS (SELECT 1) INSERT INTO orders SELECT * FROM x", "forbidden_statement"),
        ("SELECT 1; DROP TABLE orders", "multiple_statements"),
        ("SELECT 1; SELECT 2", "multiple_statements"),
        ("SELECT * FROM sqlite_master", "table_not_allowed"),
        ("SELECT * FROM main.orders", "table_not_allowed"),
        ("SELECT load_extension('/tmp/evil.so')", "forbidden_function"),
        ("SELECT * FROM pragma_table_info('orders')", "forbidden_function"),
        ("SELECT sqlite_version()", "forbidden_function"),
    ],
)
def test_security_violations_are_rejected(sql, code, schema):
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, schema)
    assert exc.value.category == ErrorCategory.SECURITY
    assert exc.value.code == code


@pytest.mark.parametrize(
    "sql, code",
    [
        ("SELECT * FROM order", "unknown_table"),  # singular typo of a real table
        ("SELECT * FROM ordrs", "unknown_table"),
        ("SELECT amount FROM orders", "unknown_column"),
        ("SELECT o.amount FROM orders o", "unknown_column"),
        ("SELECT z.name FROM products p", "unknown_column"),
        ("SELEC * FROM orders", "sql_syntax_error"),
        ("", "empty_sql"),
    ],
)
def test_schema_mistakes_are_recoverable(sql, code, schema):
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, schema)
    assert exc.value.category == ErrorCategory.RECOVERABLE
    assert exc.value.code == code


def test_unknown_column_message_helps_the_llm(schema):
    with pytest.raises(SQLValidationError) as exc:
        validate_sql("SELECT o.amount FROM orders o", schema)
    assert "order_date" in exc.value.message  # lists the real columns


def test_existing_but_unapproved_table_is_a_security_violation(tmp_path):
    path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE orders (order_id INTEGER PRIMARY KEY);"
        "CREATE TABLE salaries (id INTEGER PRIMARY KEY, amount REAL);"
    )
    conn.close()
    schema = inspect_schema(create_readonly_engine(f"sqlite:///{path}"), ["orders"])
    assert [t.name for t in schema.tables] == ["orders"]
    with pytest.raises(SQLValidationError) as exc:
        validate_sql("SELECT amount FROM salaries", schema)
    assert exc.value.category == ErrorCategory.SECURITY


@pytest.mark.parametrize(
    "sql, bad_value",
    [
        ("SELECT COUNT(*) AS n FROM orders WHERE status = 'Completed'", "Completed"),  # wrong case
        ("SELECT COUNT(*) AS n FROM orders o WHERE o.status NOT IN ('cancelled', 'refund')", "refund"),
        ("SELECT COUNT(*) AS n FROM customers c WHERE c.city = 'Bangalore'", "Bangalore"),
        ("SELECT COUNT(*) AS n FROM orders WHERE payment_method <> 'credit_card'", "credit_card"),
        ("SELECT COUNT(*) AS n FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
         "WHERE segment = 'SMB'", "SMB"),
    ],
)
def test_unknown_categorical_values_are_recoverable(sql, bad_value, schema):
    """A wrong literal would run 'successfully' and silently return 0 rows."""
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, schema)
    assert exc.value.code == "unknown_value"
    assert exc.value.category == ErrorCategory.RECOVERABLE
    assert f"'{bad_value}'" in exc.value.message


def test_unknown_value_message_suggests_exact_spelling(schema):
    with pytest.raises(SQLValidationError) as exc:
        validate_sql("SELECT COUNT(*) AS n FROM orders WHERE status = 'Completed'", schema)
    assert "Did you mean 'completed'?" in exc.value.message


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM orders WHERE status = 'completed'",
        "SELECT COUNT(*) AS n FROM orders WHERE 'completed' = status",
        "SELECT COUNT(*) AS n FROM orders o WHERE o.status IN ('cancelled', 'refunded')",
        # high-cardinality columns have no known value set, so any literal is allowed
        "SELECT COUNT(*) AS n FROM products WHERE name = 'Not A Product'",
        "SELECT COUNT(*) AS n FROM orders WHERE order_date = '2026-01-01'",
    ],
)
def test_valid_or_unknowable_values_pass(sql, schema):
    validate_sql(sql, schema)
