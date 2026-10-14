"""Text-to-SQL evaluation runner.

Runs every question in eval/dataset.json through the real QueryPilot pipeline
(with the cache bypassed) and compares the result rows with the rows produced
by the hand-written reference SQL on the same database.

Why compare results instead of SQL text? Many different SQL queries are
correct. What matters is whether the *answer* is right ("execution accuracy").
A query that runs without error is NOT automatically correct - we measure both.

Comparison rules (see `results_match`):
* Each column listed in `compare` of the expected result must match some
  column of the model's result by value (names may differ; extra columns OK).
* Row counts must be equal.
* Numbers match within 0.01 absolute (money is rounded to cents) or 1e-6
  relative; `ordered=false` compares as sorted multisets.

Usage (from backend/):
    python -m scripts.evaluate                    # uses the configured provider
    python -m scripts.evaluate --provider mock    # offline pipeline check
Writes eval/results/<provider>-<timestamp>.json and .md
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.container import build_container
from app.db.database import create_readonly_engine

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"


def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    return str(value).strip().lower()


def _equal(a: Any, b: Any) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(0.011, 1e-6 * abs(b))
    return a == b


def _sort_key(v: Any):
    v = _norm(v)
    return (0, v, "") if isinstance(v, float) else (1, 0.0, "" if v is None else v)


def _column(rows: list[list[Any]], i: int) -> list[Any]:
    return [row[i] for row in rows]


def _columns_equal(expected: list[Any], actual: list[Any], ordered: bool) -> bool:
    if len(expected) != len(actual):
        return False
    if not ordered:
        expected = sorted(expected, key=_sort_key)
        actual = sorted(actual, key=_sort_key)
    return all(_equal(e, a) for e, a in zip(expected, actual))


def results_match(expected_rows, actual_rows, compare: list[int], ordered: bool) -> tuple[bool, str]:
    """True if the model's rows contain the expected columns with the same values.

    1. Map each compared expected column to an actual column with the same
       multiset of values (column names may differ, extra columns are fine).
    2. Project both results onto those columns and compare whole rows - as
       sorted lists when order doesn't matter - so values stay paired per row.
    """
    if len(expected_rows) != len(actual_rows):
        return False, f"row count {len(actual_rows)} != expected {len(expected_rows)}"
    if not expected_rows:
        return True, "both empty"

    n_actual_cols = len(actual_rows[0])
    mapping: dict[int, int] = {}
    for idx in compare:
        want = _column(expected_rows, idx)
        match = next(
            (j for j in range(n_actual_cols)
             if j not in mapping.values() and _columns_equal(want, _column(actual_rows, j), False)),
            None,
        )
        if match is None:
            return False, f"no column matches expected column #{idx}"
        mapping[idx] = match

    def project(rows, cols):
        return [tuple(row[c] for c in cols) for row in rows]

    exp_rows = project(expected_rows, list(mapping.keys()))
    act_rows = project(actual_rows, list(mapping.values()))
    if not ordered:
        exp_rows = sorted(exp_rows, key=lambda r: [_sort_key(v) for v in r])
        act_rows = sorted(act_rows, key=lambda r: [_sort_key(v) for v in r])
    for e, a in zip(exp_rows, act_rows):
        if not all(_equal(x, y) for x, y in zip(e, a)):
            return False, "values differ" + (" or rows are in a different order" if ordered else "")
    return True, "match"


def run(settings: Settings, provider_override: str | None) -> dict:
    if provider_override:
        settings = settings.model_copy(update={"llm_provider": provider_override})
    # Keep eval requests out of the user's real history.
    tmp_meta = Path(tempfile.mkdtemp()) / "eval_meta.db"
    settings = settings.model_copy(update={"metadata_database_url": f"sqlite:///{tmp_meta}",
                                           "rate_limit_per_minute": 0})
    container = build_container(settings)
    dataset = json.loads((EVAL_DIR / "dataset.json").read_text())
    engine = create_readonly_engine(settings.database_url)

    cases = []
    for item in dataset["questions"]:
        with engine.connect() as conn:
            raw = conn.connection.dbapi_connection
            expected = [list(r) for r in raw.execute(item["reference_sql"]).fetchall()]
        response = container.query_service.run(item["question"], use_cache=False)
        executed = response.status == "success"
        correct, reason = (False, response.error.message if response.error else response.status)
        if executed:
            correct, reason = results_match(expected, response.rows, item["compare"], item["ordered"])
        cases.append({
            "id": item["id"],
            "question": item["question"],
            "status": response.status,
            "executed": executed,
            "correct": correct,
            "reason": reason,
            "retry_count": response.retry_count,
            "attempts": len(response.attempts),
            "failure_category": None if correct else (
                response.error.code if response.error else "wrong_result"),
            "latency_ms": response.timings.total_ms,
            "cost_usd": response.usage.estimated_cost_usd,
            "cost_status": response.usage.cost_status,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "generated_sql": response.sql,
            "expected_rows": expected,
            "actual_rows": response.rows[:20],
        })

    n = len(cases)
    retried = [c for c in cases if c["retry_count"] > 0]
    costs = [c["cost_usd"] for c in cases if c["cost_status"] == "estimated"]
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "provider": container.provider.name,
        "model": container.provider.model,
        "is_real_llm": container.provider.is_real_llm,
        "questions": n,
        "summary": {
            "execution_success_rate": round(sum(c["executed"] for c in cases) / n, 4),
            "correct_result_rate": round(sum(c["correct"] for c in cases) / n, 4),
            "executed_but_wrong": sum(1 for c in cases if c["executed"] and not c["correct"]),
            "questions_needing_retry": len(retried),
            "retry_success_rate": (
                round(sum(c["executed"] for c in retried) / len(retried), 4) if retried else None
            ),
            "failure_categories": dict(Counter(c["failure_category"] for c in cases if not c["correct"])),
            "avg_latency_ms": round(statistics.mean(c["latency_ms"] for c in cases), 2),
            "total_estimated_cost_usd": round(sum(costs), 6) if len(costs) == n else None,
            "cost_note": "estimated from list prices" if len(costs) == n
            else f"cost available for {len(costs)}/{n} questions (provider did not report usage)",
        },
        "cases": cases,
    }


def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# Evaluation run - {report['provider']} / {report['model']}",
        "",
        f"Run at {report['run_at']} on {report['questions']} questions.",
        "",
    ]
    if not report["is_real_llm"]:
        lines += ["> **Mock provider**: SQL comes from pre-written rules, not an LLM. This run checks "
                  "the pipeline (validation, execution, comparison), not model accuracy.", ""]
    lines += [
        "| Metric | Value |", "|---|---|",
        f"| Execution success rate | {s['execution_success_rate']:.0%} |",
        f"| Correct result rate | {s['correct_result_rate']:.0%} |",
        f"| Executed but wrong | {s['executed_but_wrong']} |",
        f"| Questions needing a retry | {s['questions_needing_retry']} |",
        f"| Retry success rate | {'-' if s['retry_success_rate'] is None else f'{s['retry_success_rate']:.0%}'} |",
        f"| Average latency | {s['avg_latency_ms']:.0f} ms |",
        f"| Total estimated cost | {'unavailable' if s['total_estimated_cost_usd'] is None else f'${s['total_estimated_cost_usd']:.4f}'} |",
        "",
        f"Failure categories: {s['failure_categories'] or 'none'}",
        "",
        "| # | Question | Status | Correct | Retries | Latency | Note |", "|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(report["cases"], 1):
        lines.append(
            f"| {i} | {c['question']} | {c['status']} | {'yes' if c['correct'] else 'no'} | "
            f"{c['retry_count']} | {c['latency_ms']:.0f} ms | {c['reason'][:80]} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["anthropic", "openai", "mock"], default=None)
    args = parser.parse_args()
    report = run(get_settings(), args.provider)
    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = out_dir / f"{report['provider']}-{stamp}"
    base.with_suffix(".json").write_text(json.dumps(report, indent=2, default=str))
    base.with_suffix(".md").write_text(to_markdown(report))
    print(to_markdown(report))
    print(f"Saved {base}.json and .md")


if __name__ == "__main__":
    main()
