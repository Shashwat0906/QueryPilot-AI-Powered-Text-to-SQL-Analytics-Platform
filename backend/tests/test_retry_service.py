import pytest

from app.core.errors import LLMProviderError
from app.services.query_executor import QueryExecutor
from app.services.retry_service import RetryService
from app.services.sql_generator import SQLGenerator
from tests.conftest import APPROVED
from tests.fakes import UNANSWERABLE, ScriptedProvider, sql_reply

GOOD = "SELECT COUNT(*) AS n FROM orders"


@pytest.fixture
def make_service(engine):
    def _make(*replies, max_corrections=2):
        provider = ScriptedProvider(list(replies))
        service = RetryService(
            SQLGenerator(provider), QueryExecutor(engine, APPROVED),
            max_corrections=max_corrections, max_rows=100, timeout_seconds=5,
        )
        return service, provider

    return _make


def test_success_on_first_attempt(make_service, schema):
    service, provider = make_service(sql_reply(GOOD))
    result = service.run("How many orders?", schema)
    assert result.status == "success"
    assert result.retry_count == 0
    assert result.execution.rows == [[1600]]
    assert [a.status for a in result.attempts] == ["success"]
    assert len(result.llm_calls) == 1


def test_recovers_from_unknown_column(make_service, schema):
    service, provider = make_service(
        sql_reply("SELECT SUM(amount) AS total FROM orders"),  # validator: unknown column
        sql_reply(GOOD),
    )
    result = service.run("How many orders?", schema)
    assert result.status == "success"
    assert result.retry_count == 1
    assert [a.status for a in result.attempts] == ["validation_error", "success"]
    # The correction prompt carries the previous SQL and the sanitized error only.
    purpose, prompt = provider.prompts[1]
    assert purpose == "correction"
    assert "SUM(amount)" in prompt and "Unknown column 'amount'" in prompt
    assert "Traceback" not in prompt


def test_recovers_from_database_runtime_error(make_service, schema):
    service, _ = make_service(
        sql_reply("SELECT SUM(SUM(quantity)) AS x FROM order_items"),  # passes validator, fails in SQLite
        sql_reply(GOOD),
    )
    result = service.run("q", schema)
    assert result.status == "success"
    assert [a.status for a in result.attempts] == ["execution_error", "success"]


def test_retries_are_bounded_and_exhaust(make_service, schema):
    bad = sql_reply("SELECT nope FROM orders")
    service, provider = make_service(bad, bad, bad, bad)
    result = service.run("q", schema)
    assert result.status == "failed"
    assert result.error.code == "retries_exhausted"
    assert len(result.attempts) == 3  # 1 generation + 2 corrections, never more
    assert result.retry_count == 2
    assert len(provider.replies) == 1  # the 4th reply was never requested


def test_zero_corrections_configuration(make_service, schema):
    service, _ = make_service(sql_reply("SELECT nope FROM orders"), max_corrections=0)
    result = service.run("q", schema)
    assert result.status == "failed" and len(result.attempts) == 1


def test_security_violation_is_not_retried(make_service, schema):
    service, provider = make_service(sql_reply("DELETE FROM orders"), sql_reply(GOOD))
    result = service.run("Delete everything", schema)
    assert result.status == "rejected"
    assert len(result.attempts) == 1
    assert result.attempts[0].status == "security_violation"
    assert result.error.category == "security"
    assert len(provider.replies) == 1  # no correction was requested


def test_correction_that_becomes_unsafe_is_rejected(make_service, schema):
    service, _ = make_service(sql_reply("SELECT nope FROM orders"), sql_reply("DROP TABLE orders"))
    result = service.run("q", schema)
    assert result.status == "rejected"
    assert [a.status for a in result.attempts] == ["validation_error", "security_violation"]


def test_malformed_llm_output_triggers_correction(make_service, schema):
    service, _ = make_service(None, {"answerable": True}, sql_reply(GOOD))
    result = service.run("q", schema)
    assert result.status == "success"
    assert [a.status for a in result.attempts] == ["parse_error", "parse_error", "success"]
    assert len(result.llm_calls) == 3  # tokens of malformed replies are still counted


def test_unanswerable_question(make_service, schema):
    service, _ = make_service(UNANSWERABLE)
    result = service.run("What's the weather?", schema)
    assert result.status == "unanswerable"
    assert "weather" in result.error.message


def test_provider_outage_stops_without_retry(make_service, schema):
    service, _ = make_service(LLMProviderError("The Anthropic API timed out."))
    result = service.run("q", schema)
    assert result.status == "failed"
    assert result.error.category == "provider"
    assert len(result.attempts) == 1


TOP5 = (
    "SELECT p.name, SUM(oi.quantity) AS units FROM order_items oi "
    "JOIN products p ON p.product_id = oi.product_id GROUP BY p.name ORDER BY units DESC"
)


def test_result_with_too_many_rows_is_corrected(make_service, schema):
    service, provider = make_service(sql_reply(TOP5), sql_reply(TOP5 + " LIMIT 5"))
    result = service.run("Which five products sold the most units?", schema)
    assert result.status == "success"
    assert [a.status for a in result.attempts] == ["result_check_failed", "success"]
    assert result.execution.row_count == 5
    assert result.warnings == []
    assert "LIMIT 5" in provider.prompts[1][1]


def test_row_count_mismatch_on_last_attempt_returns_result_with_warning(make_service, schema):
    service, _ = make_service(sql_reply(TOP5), max_corrections=0)
    result = service.run("Which five products sold the most units?", schema)
    assert result.status == "success"
    assert result.execution.row_count == 36
    assert len(result.warnings) == 1 and "asks for 5" in result.warnings[0]


def test_wrong_categorical_value_is_corrected_before_execution(make_service, schema):
    service, provider = make_service(
        sql_reply("SELECT COUNT(*) AS n FROM orders WHERE status = 'Cancelled'"),
        sql_reply("SELECT COUNT(*) AS n FROM orders WHERE status = 'cancelled'"),
    )
    result = service.run("How many orders were cancelled?", schema)
    assert result.status == "success"
    assert result.execution.rows == [[104]]
    assert [a.error_code for a in result.attempts] == ["unknown_value", None]
    assert "Did you mean 'cancelled'?" in provider.prompts[1][1]


def test_revenue_business_rule_is_enforced(make_service, schema):
    no_rule = ("SELECT ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS total_revenue "
               "FROM order_items oi")
    fixed = (no_rule + " JOIN orders o ON o.order_id = oi.order_id "
             "WHERE o.status NOT IN ('cancelled', 'refunded')")
    service, provider = make_service(sql_reply(no_rule), sql_reply(fixed))
    result = service.run("What is our total revenue?", schema)
    assert result.status == "success"
    assert [a.error_code for a in result.attempts] == ["business_rule_violation", None]
    assert abs(result.execution.rows[0][0] - 455614.72) < 0.011
