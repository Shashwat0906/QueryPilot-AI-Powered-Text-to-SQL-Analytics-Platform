"""Aggregate metrics computed from the real request log.

Nothing here is hard-coded: every number is derived from rows recorded by
`HistoryService`. With no requests yet, rates are `None` (shown as "-" in the
UI) rather than 0%, so an empty system is not mistaken for a failing one.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean

from app.models.request_log import RequestLog


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[index], 2)


def _utc_iso(value: datetime) -> str:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def compute_analytics(logs: list[RequestLog], recent_limit: int = 50) -> dict:
    total = len(logs)
    success = sum(1 for log in logs if log.status == "success")
    rejected = sum(1 for log in logs if log.status == "rejected")
    unanswerable = sum(1 for log in logs if log.status == "unanswerable")
    failed = total - success
    cache_hits = sum(1 for log in logs if log.cache_hit)
    fresh = [log for log in logs if not log.cache_hit]  # requests that ran the pipeline
    with_retry = [log for log in fresh if log.retry_count > 0]
    retried_and_succeeded = sum(1 for log in with_retry if log.status == "success")

    latencies = [log.total_ms for log in logs]
    # Only requests that actually called an LLM and got a price estimate.
    # Cache hits ($0, no LLM calls) are counted separately so they don't hide
    # requests whose cost is unknown.
    priced = [log for log in logs if log.cost_status == "estimated"]
    unpriced = sum(1 for log in logs if log.cost_status == "unavailable")
    tokens_known = [log for log in priced if log.input_tokens is not None]

    by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"success": 0, "failed": 0, "cost": 0.0})
    for log in logs:
        day = log.created_at.date().isoformat()
        by_day[day]["success" if log.status == "success" else "failed"] += 1
        by_day[day]["cost"] += log.estimated_cost_usd or 0.0

    failure_categories = Counter(
        log.error_code or log.status for log in logs if log.status != "success"
    )

    recent = logs[-recent_limit:]
    return {
        "total_requests": total,
        "successful_requests": success,
        "failed_requests": failed,
        "rejected_requests": rejected,
        "unanswerable_requests": unanswerable,
        "success_rate": _rate(success, total),
        "avg_latency_ms": round(mean(latencies), 2) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 95),
        "avg_generation_ms": round(mean(l.generation_ms for l in fresh), 2) if fresh else None,
        "avg_db_ms": round(mean(l.db_ms for l in fresh), 2) if fresh else None,
        "total_estimated_cost_usd": round(sum(l.estimated_cost_usd for l in priced), 6) if priced else None,
        "avg_estimated_cost_per_request_usd": (
            round(sum(l.estimated_cost_usd for l in priced) / len(priced), 6) if priced else None
        ),
        "priced_requests": len(priced),
        "unpriced_requests": unpriced,
        "retry_rate": _rate(len(with_retry), len(fresh)),
        "retry_success_rate": _rate(retried_and_succeeded, len(with_retry)),
        "total_retries": sum(l.retry_count for l in logs),
        "cache_hits": cache_hits,
        "cache_hit_rate": _rate(cache_hits, total),
        "total_input_tokens": sum(l.input_tokens for l in tokens_known) if tokens_known else None,
        "total_output_tokens": sum(l.output_tokens or 0 for l in tokens_known) if tokens_known else None,
        "token_usage_available_requests": len(tokens_known),
        "llm_calls": sum(l.llm_calls for l in logs),
        "requests_by_day": [
            {"date": day, "success": int(v["success"]), "failed": int(v["failed"]),
             "cost_usd": round(v["cost"], 6)}
            for day, v in sorted(by_day.items())
        ],
        "failure_categories": [
            {"category": cat, "count": n} for cat, n in failure_categories.most_common()
        ],
        "recent_requests": [
            {
                "request_id": l.request_id,
                "created_at": _utc_iso(l.created_at),
                "total_ms": l.total_ms,
                "generation_ms": l.generation_ms,
                "db_ms": l.db_ms,
                "status": l.status,
                "cache_hit": l.cache_hit,
                "retry_count": l.retry_count,
                "estimated_cost_usd": l.estimated_cost_usd,
                "input_tokens": l.input_tokens,
                "output_tokens": l.output_tokens,
            }
            for l in recent
        ],
    }
