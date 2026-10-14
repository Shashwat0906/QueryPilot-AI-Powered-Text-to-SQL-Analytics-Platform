import pytest

from app.services.result_checks import check_revenue_rule, check_row_count, requested_row_count


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Show the top five products by revenue.", 5),
        ("top 10 customers by spend", 10),
        ("Which two cities have the most customers?", 2),
        ("Show the IDs of the five customers who placed the most orders", 5),
        ("List 3 categories with the lowest revenue", 3),
        ("What 3 categories sold best in the last 6 months?", 3),
        # not a request for N rows:
        ("What was our monthly revenue over the last six months?", None),
        ("Revenue for the past 3 weeks by day", None),
        ("Show 6 months of revenue", None),
        ("How many orders did each customer segment place in 2026?", None),
        ("Which 2026 months had the most orders?", None),
        ("orders with more than 3 items", None),
        ("What is our total revenue?", None),
        # a single winner, implied by a singular noun + superlative:
        ("Which customer segment generated the most revenue?", 1),
        ("Which city has the most customers?", 1),
        ("Which customers placed the most orders?", None),  # plural -> a list
        ("Which categories have the highest revenue?", None),
    ],
)
def test_requested_row_count(question, expected):
    assert requested_row_count(question) == expected


def test_check_only_flags_too_many_rows():
    q = "Show the top five products by revenue."
    assert check_row_count(q, 5) is None
    assert check_row_count(q, 3) is None  # fewer may legitimately exist
    problem = check_row_count(q, 10)
    assert problem and "LIMIT 5" in problem
    assert check_row_count("What is our total revenue?", 999) is None


REVENUE_NO_STATUS = (
    "SELECT ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue FROM order_items oi"
)


def test_revenue_without_status_rule_is_flagged():
    problem = check_revenue_rule("What is our total revenue?", REVENUE_NO_STATUS)
    assert problem and "cancelled" in problem


def test_revenue_rule_respects_explicit_intent_and_existing_filters():
    assert check_revenue_rule("Gross revenue including refunded orders?", REVENUE_NO_STATUS) is None
    assert check_revenue_rule("Revenue from cancelled orders", REVENUE_NO_STATUS) is None
    with_filter = REVENUE_NO_STATUS + " JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 'completed'"
    assert check_revenue_rule("What is our total revenue?", with_filter) is None
    assert check_revenue_rule("How many units were sold?", "SELECT SUM(quantity) FROM order_items") is None
