"""Fault-injection evaluation: does the pipeline catch realistic LLM mistakes?

For every question in eval/dataset.json, take the correct reference SQL, inject
one realistic mistake (wrong casing of a value, a typo'd value, a dropped
LIMIT, a misspelled column, a dropped filter, ...) and play it through the
real RetryService as the "LLM's" first answer. A scripted fake LLM returns the
correct reference SQL if, and only if, the pipeline asks for a correction.

Each case ends in one of:
  caught    - the pipeline detected the mistake and the final answer is correct
  warned    - wrong rows returned, but with a visible warning
  missed    - the mistaken query ran and a WRONG answer was returned silently
  no_effect - the mutation happened not to change the result

This measures the safety net, not a model. No API key needed.

Usage (from backend/):  python -m scripts.fault_injection
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from app.core.config import get_settings
from app.db.database import create_readonly_engine
from app.services.query_executor import QueryExecutor
from app.services.retry_service import RetryService
from app.services.schema_service import inspect_schema
from app.services.sql_generator import SQLGenerator
from scripts.evaluate import results_match
from app.services.llm_service import LLMProvider, LLMResult


class _ReplayProvider(LLMProvider):
    """Fake LLM: answers with the given SQL strings in order (no network)."""

    name = "replay"
    model = "replay"

    def __init__(self, sqls: list[str]):
        self._sqls = list(sqls)

    def generate_json(self, system, prompt, json_schema, *, purpose):
        data = {"answerable": True, "sql": self._sqls.pop(0), "explanation": "", "tables_used": [],
                "assumptions": [], "clarification": None}
        return LLMResult(data, "", None, None, 0.0, self.model, purpose)

    def generate_text(self, system, prompt, *, purpose):
        raise NotImplementedError

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"

# (name, what an LLM got wrong, regex, replacement). Applied once per query.
MUTATIONS = [
    ("value_casing", "categorical value in the wrong case ('Completed')",
     r"'(completed|cancelled|refunded)'", lambda m: f"'{m.group(1).capitalize()}'"),
    ("value_typo", "near-miss categorical value ('refund', 'complete')",
     r"'(refunded|completed|cancelled)'",
     lambda m: {"refunded": "'refund'", "completed": "'complete'", "cancelled": "'canceled'"}[m.group(1)]),
    ("unknown_column", "misspelled column (quantity -> qty)", r"\bquantity\b", lambda m: "qty"),
    ("dropped_limit", "ignored the requested number of rows (LIMIT removed)",
     r"\s+LIMIT\s+\d+\s*$", lambda m: ""),
    ("dropped_status_filter", "forgot the revenue status rule (counts refunds as revenue)",
     r"\s+WHERE o\.status NOT IN \('cancelled', 'refunded'\)( AND)?",
     lambda m: " WHERE" if m.group(1) else ""),
    ("wrong_date_boundary", "off-by-one date range ('last six months' from 29 Mar)",
     r"'2026-04-01'", lambda m: "'2026-03-29'"),
    ("wrong_measure", "counted rows instead of summing units", r"SUM\(oi\.quantity\)", lambda m: "COUNT(*)"),
]


def run() -> dict:
    settings = get_settings()
    engine = create_readonly_engine(settings.database_url)
    schema = inspect_schema(engine, settings.approved_tables)
    executor = QueryExecutor(engine, settings.approved_tables)
    dataset = json.loads((EVAL_DIR / "dataset.json").read_text())

    cases = []
    for item in dataset["questions"]:
        reference = item["reference_sql"]
        with engine.connect() as conn:
            expected = [list(r) for r in conn.connection.dbapi_connection.execute(reference).fetchall()]
        for name, description, pattern, repl in MUTATIONS:
            mutated, n = re.subn(pattern, repl, reference, count=1)
            if n == 0 or mutated == reference:
                continue
            provider = _ReplayProvider([mutated, reference, reference])
            service = RetryService(SQLGenerator(provider), executor, max_corrections=2,
                                   max_rows=settings.max_result_rows, timeout_seconds=5)
            result = service.run(item["question"], schema)
            caught_by = next((a.error_code for a in result.attempts if a.status != "success"), None)
            correct = result.status == "success" and results_match(
                expected, result.execution.rows, item["compare"], item["ordered"])[0]
            if caught_by and correct:
                outcome = "caught"
            elif correct:
                outcome = "no_effect"
            elif result.warnings:
                outcome = "warned"
            else:
                outcome = "missed"
            cases.append({"question_id": item["id"], "mutation": name, "description": description,
                          "outcome": outcome, "caught_by": caught_by, "mutated_sql": mutated})

    summary: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for c in cases:
        summary[c["mutation"]][c["outcome"]] += 1
        summary[c["mutation"]]["total"] += 1
        summary[c["mutation"]]["caught_by"] = c["caught_by"] or summary[c["mutation"]].get("caught_by")
    return {"cases": cases, "summary": {k: dict(v) for k, v in summary.items()}}


def to_markdown(report: dict) -> str:
    descriptions = {m[0]: m[1] for m in MUTATIONS}
    lines = [
        "# Fault-injection evaluation",
        "",
        "Correct reference SQL with one realistic LLM mistake injected, played through the real "
        "pipeline. *caught* = detected and corrected to the right answer; *missed* = a wrong "
        "answer was returned silently; *no effect* = the mistake didn't change the result.",
        "",
        "| Mistake | Cases | Caught | Missed | No effect | Detected by |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in report["summary"].items():
        lines.append(
            f"| {descriptions[name]} | {s['total']} | {s.get('caught', 0)} | "
            f"{s.get('missed', 0) + s.get('warned', 0)} | {s.get('no_effect', 0)} | "
            f"{s.get('caught_by') or '-'} |"
        )
    total = len(report["cases"])
    harmful = [c for c in report["cases"] if c["outcome"] != "no_effect"]
    caught = sum(1 for c in harmful if c["outcome"] == "caught")
    lines += ["", f"Mistakes that changed the answer: {len(harmful)} of {total}. "
              f"Caught: {caught}. Missed: {len(harmful) - caught}."]
    return "\n".join(lines) + "\n"


def main() -> None:
    report = run()
    out = EVAL_DIR / "results" / "fault-injection.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(to_markdown(report))
    print(to_markdown(report))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
