"""Turn query results into a short natural-language answer.

Grounding: the answer is written ONLY from the rows the database returned.
* `llm` mode sends the question, the executed SQL, the column names and the
  first N rows to the model and asks for 1-3 sentences using only those
  numbers.
* `template` mode (and the fallback when the LLM call fails, or for the mock
  provider) builds the sentence deterministically in Python.

Either way, zero rows produces "No matching records were found." - the model
is never asked to describe an empty result, so it cannot invent one.
"""

from __future__ import annotations

import json
import logging

from app.core.errors import LLMProviderError
from app.services.llm_service import LLMProvider, LLMResult
from app.services.query_executor import ExecutionResult

logger = logging.getLogger(__name__)

ANSWER_SYSTEM = """You write the answer to a business question from SQL query results.
Use ONLY the numbers and names in the provided rows - never estimate, extrapolate or invent.
Write 1-3 plain sentences for a non-technical reader. Format money as USD with 2 decimals and
thousands separators. If the rows were truncated, say the answer is based on the rows shown.
Do not mention SQL, tables or columns."""


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def template_answer(question: str, execution: ExecutionResult) -> str:  # noqa: ARG001
    if execution.row_count == 0:
        return "No matching records were found."
    cols = [c.name for c in execution.columns]
    first = execution.rows[0]
    if execution.row_count == 1 and len(cols) == 1:
        return f"The result is {_fmt(first[0])} ({cols[0].replace('_', ' ')})."
    if execution.row_count == 1:
        pairs = ", ".join(f"{c.replace('_', ' ')}: {_fmt(v)}" for c, v in zip(cols, first))
        return f"The query returned one row - {pairs}."
    lead = ", ".join(f"{c.replace('_', ' ')}: {_fmt(v)}" for c, v in zip(cols, first))
    more = " (results truncated at the row limit)" if execution.truncated else ""
    return f"The query returned {execution.row_count:,} rows{more}. First row - {lead}."


class AnswerService:
    def __init__(self, provider: LLMProvider, mode: str, preview_rows: int):
        self.provider = provider
        self.mode = mode
        self.preview_rows = preview_rows

    def answer(self, question: str, sql: str, execution: ExecutionResult) -> tuple[str, LLMResult | None]:
        if execution.row_count == 0:
            return "No matching records were found.", None
        if self.mode != "llm" or not self.provider.is_real_llm:
            return template_answer(question, execution), None

        payload = {
            "columns": [c.name for c in execution.columns],
            "rows": execution.rows[: self.preview_rows],
            "total_rows_returned": execution.row_count,
            "rows_shown": min(execution.row_count, self.preview_rows),
            "truncated_at_row_limit": execution.truncated,
        }
        prompt = (
            f"<question>{question}</question>\n<sql>{sql}</sql>\n"
            f"<results>{json.dumps(payload, default=str)}</results>\n"
            "Answer the question from these results."
        )
        try:
            call = self.provider.generate_text(ANSWER_SYSTEM, prompt, purpose="answer")
        except LLMProviderError as exc:
            # The data is already correct; a failed summary should not fail the request.
            logger.warning("Answer generation failed, using template: %s", exc.message)
            return template_answer(question, execution), None
        return call.text or template_answer(question, execution), call
