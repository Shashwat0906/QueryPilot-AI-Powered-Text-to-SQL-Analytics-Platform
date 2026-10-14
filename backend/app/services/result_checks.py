"""Sanity checks: does the query answer the question that was asked?

A query can run without any error and still answer a different question.
Static validation can't see that, but some mismatches are visible in the
*shape* of the result. The check here is deliberately narrow so it almost
never fires wrongly:

* Row count: the question explicitly asks for N items ("top five products",
  "which two cities", "the 3 customers who ...") or for a single winner
  ("which segment generated the most revenue") but the query returned MORE
  rows. Fewer rows is fine - there may genuinely be fewer.
* Business rule (checked before execution): a query that computes revenue
  (quantity * unit_price * discount) must apply the order-status rule, or it
  silently counts cancelled and refunded orders. Skipped when the question
  itself talks about status, refunds, cancellations or gross figures.

Time phrases ("last six months", "past 3 weeks") are not row requests and are
ignored. A violation is fed back to the LLM as a recoverable error; if no
correction attempts are left, the result is returned with a warning instead.
"""

from __future__ import annotations

import re

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
}
_NUM = r"(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")"
_TIME_UNITS = r"(?:second|minute|hour|day|week|month|quarter|year)s?\b"
# "top 5", "first five", "which two", "what 3", "the five", "show 10"
_PATTERN = re.compile(
    rf"\b(?:top|first|bottom|which|what|the|show|list|name)\s+{_NUM}\b(?!\s+{_TIME_UNITS})",
    re.IGNORECASE,
)


# "Which segment generated the most ...", "which city has the highest ..." -
# a singular noun (not ending in s) followed by a superlative means one row.
_SINGLE_WINNER = re.compile(
    r"\bwhich\s+(?:\w+\s+)?\w*[^s\s]\s+(?:has|had|is|was|generated|made|brought|earned|sold|"
    r"placed|received|spent|got)\s+the\s+(?:most|highest|largest|biggest|best|lowest|least|fewest)\b",
    re.IGNORECASE,
)


def requested_row_count(question: str) -> int | None:
    """Number of items the question asks for, or None if it doesn't say."""
    for match in _PATTERN.finditer(question):
        token = match.group(1).lower()
        value = int(token) if token.isdigit() else NUMBER_WORDS[token]
        if 0 < value <= 100:
            return value
    if _SINGLE_WINNER.search(question):
        return 1
    return None


def check_row_count(question: str, row_count: int) -> str | None:
    """Return a problem description if the result has more rows than requested."""
    wanted = requested_row_count(question)
    if wanted is None or row_count <= wanted:
        return None
    return (
        f"The question asks for {wanted} item(s) but the query returned {row_count} rows. "
        f"Order by the ranking measure and add LIMIT {wanted}."
    )


_REVENUE_PARTS = ("quantity", "unit_price", "discount")
_STATUS_TOPIC = re.compile(
    r"\b(?:status|cancel\w*|refund\w*|gross|including|all orders|every order|pending|shipped|completed)\b",
    re.IGNORECASE,
)


def check_revenue_rule(question: str, sql: str) -> str | None:
    """Revenue computed without the order-status rule -> problem description."""
    lowered = sql.lower()
    computes_revenue = all(part in lowered for part in _REVENUE_PARTS)
    if not computes_revenue or "status" in lowered or _STATUS_TOPIC.search(question):
        return None
    return (
        "The query computes revenue but does not apply the business rule: orders with status "
        "'cancelled' or 'refunded' must be excluded (join orders and filter o.status)."
    )
