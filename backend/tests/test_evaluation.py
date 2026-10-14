import json
from pathlib import Path

import pytest

from app.services.query_executor import QueryExecutor
from app.services.sql_validator import validate_sql
from scripts.evaluate import results_match
from tests.conftest import APPROVED

DATASET = json.loads((Path(__file__).resolve().parents[1] / "eval" / "dataset.json").read_text())


def test_dataset_has_at_least_ten_unique_questions():
    ids = [q["id"] for q in DATASET["questions"]]
    assert len(ids) >= 10 and len(set(ids)) == len(ids)


@pytest.mark.parametrize("item", DATASET["questions"], ids=lambda q: q["id"])
def test_reference_sql_is_valid_and_returns_rows(item, schema, engine):
    validated = validate_sql(item["reference_sql"], schema)
    result = QueryExecutor(engine, APPROVED).execute(validated.sql, max_rows=500, timeout_seconds=5)
    assert result.row_count > 0
    assert max(item["compare"]) < len(result.columns)


def test_match_tolerates_names_extra_columns_and_float_noise():
    expected = [["Books", 100.0], ["Office", 50.5]]
    actual = [[2, "office", 50.504, "x"], [1, "BOOKS", 99.999, "y"]]
    assert results_match(expected, actual, [0, 1], ordered=False)[0]


def test_match_requires_order_when_ordered():
    expected = [["a", 2], ["b", 1]]
    assert results_match(expected, [["a", 2], ["b", 1]], [0, 1], ordered=True)[0]
    assert not results_match(expected, [["b", 1], ["a", 2]], [0, 1], ordered=True)[0]


def test_match_keeps_values_paired_per_row():
    expected = [["India", 90], ["USA", 30]]
    swapped = [["India", 30], ["USA", 90]]  # each column alone matches, rows do not
    assert not results_match(expected, swapped, [0, 1], ordered=False)[0]


def test_match_rejects_wrong_row_count_and_values():
    assert not results_match([[1]], [[1], [2]], [0], ordered=False)[0]
    assert not results_match([[455614.72]], [[455000.0]], [0], ordered=False)[0]


def _ref_rows(engine, qid):
    sql = next(q["reference_sql"] for q in DATASET["questions"] if q["id"] == qid)
    with engine.connect() as conn:
        return [list(r) for r in conn.connection.dbapi_connection.execute(sql).fetchall()]


def test_reference_answers_match_independent_python_recomputation(engine):
    """Recompute key expected answers from raw rows without SQL aggregation."""
    with engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        orders = {r[0]: r for r in raw.execute("SELECT order_id, status FROM orders")}
        items = raw.execute("SELECT order_id, product_id, quantity, unit_price, discount FROM order_items").fetchall()
        category = dict(raw.execute("SELECT product_id, category FROM products").fetchall())

    revenue = sum(q * p * (1 - d) for oid, _, q, p, d in items if orders[oid][1] not in ("cancelled", "refunded"))
    # SQLite stores money as floating point; allow one cent (see docs/testing.md).
    assert abs(_ref_rows(engine, "total_revenue")[0][0] - revenue) <= 0.011

    units = {}
    for oid, pid, q, _, _ in items:
        if orders[oid][1] == "completed":
            units[category[pid]] = units.get(category[pid], 0) + q
    assert {c: u for c, u in _ref_rows(engine, "units_by_category_completed")} == units

    cancelled = sum(1 for _, status in orders.values() if status == "cancelled")
    assert _ref_rows(engine, "cancelled_orders") == [[cancelled]]


def test_fault_injection_catches_all_mechanical_mistakes():
    """Only purely semantic mistakes (date boundary, wrong aggregate) may slip through."""
    from scripts.fault_injection import run

    report = run()
    missed = {c["mutation"] for c in report["cases"] if c["outcome"] in ("missed", "warned")}
    assert missed <= {"wrong_date_boundary", "wrong_measure"}
    assert sum(1 for c in report["cases"] if c["outcome"] == "caught") >= 37
