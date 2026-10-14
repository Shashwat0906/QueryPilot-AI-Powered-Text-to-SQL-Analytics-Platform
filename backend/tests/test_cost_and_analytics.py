from datetime import datetime, timezone

import pytest

from app.models.request_log import RequestLog
from app.services.analytics_service import compute_analytics
from app.services.cost_tracker import summarize_cost
from app.services.llm_service import LLMResult

PRICING = {"claude-sonnet-5-5": {"input": 2.0, "output": 10.0}}


def call(tokens_in, tokens_out, purpose="generation"):
    return LLMResult(None, "", tokens_in, tokens_out, 10.0, "claude-sonnet-5-5", purpose)


def test_cost_sums_every_call_including_corrections():
    calls = [call(1000, 200), call(1200, 150, "correction"), call(500, 80, "answer")]
    summary = summarize_cost(calls, "claude-sonnet-5-5", PRICING)
    assert summary.input_tokens == 2700
    assert summary.output_tokens == 430
    # 2700/1e6*2 + 430/1e6*10 = 0.0054 + 0.0043
    assert summary.estimated_cost_usd == pytest.approx(0.0097)
    assert summary.status == "estimated"
    assert summary.llm_calls == 3


def test_missing_token_counts_make_cost_unavailable_not_zero():
    summary = summarize_cost([call(1000, 200), call(None, None)], "claude-sonnet-5-5", PRICING)
    assert summary.estimated_cost_usd is None
    assert summary.input_tokens is None
    assert summary.status == "unavailable"


def test_unpriced_model_is_unavailable():
    summary = summarize_cost([call(100, 10)], "some-unknown-model", PRICING)
    assert summary.estimated_cost_usd is None
    assert summary.input_tokens == 100  # tokens are still known
    assert summary.status == "unavailable"


def test_no_calls_costs_nothing():
    summary = summarize_cost([], "claude-sonnet-5-5", PRICING)
    assert summary.estimated_cost_usd == 0.0 and summary.status == "no_llm_calls"


def log(**kw):
    base = dict(
        request_id=kw.pop("rid", "r"), created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        question="q", status="success", retry_count=0, llm_calls=2, provider="anthropic",
        model="m", input_tokens=1000, output_tokens=100, estimated_cost_usd=0.003,
        cost_status="estimated", generation_ms=800.0, db_ms=5.0, total_ms=1000.0, cache_hit=False,
        error_code=None,
    )
    base.update(kw)
    return RequestLog(**base)


def test_analytics_empty_state_uses_none_not_zero():
    data = compute_analytics([])
    assert data["total_requests"] == 0
    assert data["success_rate"] is None
    assert data["avg_latency_ms"] is None
    assert data["total_estimated_cost_usd"] is None
    assert data["requests_by_day"] == []


def test_analytics_aggregation():
    logs = [
        log(rid="1"),
        log(rid="2", retry_count=1, total_ms=3000.0),
        log(rid="3", status="failed", retry_count=2, error_code="retries_exhausted", total_ms=2000.0),
        log(rid="4", status="rejected", error_code="forbidden_statement"),
        log(rid="5", cache_hit=True, llm_calls=0, input_tokens=0, output_tokens=0,
            estimated_cost_usd=0.0, cost_status="no_llm_calls", total_ms=1.0),
        log(rid="6", input_tokens=None, output_tokens=None, estimated_cost_usd=None,
            cost_status="unavailable"),
    ]
    data = compute_analytics(logs)
    assert data["total_requests"] == 6
    assert data["successful_requests"] == 4
    assert data["failed_requests"] == 2
    assert data["rejected_requests"] == 1
    assert data["success_rate"] == pytest.approx(4 / 6, abs=1e-4)
    assert data["cache_hit_rate"] == pytest.approx(1 / 6, abs=1e-4)
    # retry rate counts only requests that ran the pipeline (not the cache hit)
    assert data["retry_rate"] == pytest.approx(2 / 5)
    assert data["retry_success_rate"] == 0.5
    assert data["total_retries"] == 3
    # cost: only the 4 "estimated" requests are priced; cache hit + unavailable excluded
    assert data["priced_requests"] == 4
    assert data["unpriced_requests"] == 1
    assert data["total_estimated_cost_usd"] == pytest.approx(0.012)
    assert data["avg_estimated_cost_per_request_usd"] == pytest.approx(0.003)
    assert data["total_input_tokens"] == 4000
    assert data["avg_latency_ms"] == pytest.approx((1000 + 3000 + 2000 + 1000 + 1 + 1000) / 6, abs=0.01)
    assert {c["category"] for c in data["failure_categories"]} == {"retries_exhausted",
                                                                   "forbidden_statement"}
