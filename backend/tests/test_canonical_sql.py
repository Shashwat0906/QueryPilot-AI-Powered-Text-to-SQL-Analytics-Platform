"""The validator executes sqlglot's re-rendered SQL, not the model's text.
These tests prove the re-rendering never changes what a query returns."""

import json
import sqlite3
from pathlib import Path

import pytest

from app.db.database import sqlite_path_from_url
from app.services.sql_validator import validate_sql

DATASET = json.loads((Path(__file__).resolve().parents[1] / "eval" / "dataset.json").read_text())

CORPUS = [q["reference_sql"] for q in DATASET["questions"]] + [
    "SELECT 7/2 AS i, 7.0/2 AS f, 7%3 AS m, -7/2 AS neg",
    "SELECT SUM(quantity)/COUNT(*) AS int_div, CAST(SUM(quantity) AS REAL)/COUNT(*) AS real_div FROM order_items",
    "SELECT first_name || ' ' || last_name AS n FROM customers ORDER BY n LIMIT 3",
    "SELECT IFNULL(NULL, 5) AS a, NULLIF(1, 1) AS b, IIF(1 > 0, 'y', 'n') AS c, COALESCE(NULL, NULL, 3) AS d",
    "SELECT name FROM products WHERE name LIKE '%MAT%' OR name GLOB 'S*' ORDER BY name",
    "SELECT strftime('%W', order_date) AS wk, strftime('%Y', order_date) AS y, COUNT(*) AS n "
    "FROM orders GROUP BY 1, 2 ORDER BY 2, 1 LIMIT 5",
    "SELECT date('2026-09-29', 'start of month', '-5 months') AS d1, "
    "julianday('2026-09-29') - julianday('2026-01-01') AS days",
    "SELECT order_id, shipping_fee FROM orders ORDER BY shipping_fee DESC NULLS LAST, order_id LIMIT 5",
    "SELECT CAST(unit_price AS INTEGER) AS ip, ROUND(unit_price) AS r0 FROM products ORDER BY product_id LIMIT 5",
    "SELECT CASE WHEN unit_price > 100 THEN 'high' WHEN unit_price > 40 THEN 'mid' ELSE 'low' END AS band, "
    "COUNT(*) AS n FROM products GROUP BY band ORDER BY band",
    "SELECT group_concat(name, ' | ') AS g FROM (SELECT name FROM products ORDER BY name LIMIT 3)",
    "SELECT order_id FROM orders ORDER BY order_id LIMIT 5 OFFSET 10",
    "SELECT customer_id, SUM(shipping_fee) OVER (PARTITION BY customer_id ORDER BY order_date "
    "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running FROM orders "
    "ORDER BY customer_id, order_date LIMIT 6",
    "SELECT product_id FROM products EXCEPT SELECT product_id FROM order_items",
    "SELECT status, COUNT(*) AS n FROM orders WHERE status IS NOT 'completed' GROUP BY status ORDER BY status",
    "SELECT TRUE AS t, FALSE AS f, 1 = 1 AS eq, 'a' < 'b' AS lt",
    "SELECT ROUND(AVG(n), 2) AS avg_items FROM (SELECT COUNT(*) AS n FROM order_items GROUP BY order_id)",
]


@pytest.mark.parametrize("sql", CORPUS)
def test_canonical_sql_returns_identical_results(sql, schema, business_db_url):
    canonical = validate_sql(sql, schema).sql
    conn = sqlite3.connect(sqlite_path_from_url(business_db_url))
    try:
        assert conn.execute(canonical).fetchall() == conn.execute(sql).fetchall()
    finally:
        conn.close()
