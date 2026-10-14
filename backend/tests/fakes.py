"""Test doubles: a scripted LLM that returns pre-defined replies in order."""

from __future__ import annotations

from collections import deque
from typing import Any

from app.core.errors import LLMProviderError
from app.services.llm_service import LLMProvider, LLMResult


def sql_reply(sql: str, **extra: Any) -> dict[str, Any]:
    return {
        "answerable": True,
        "sql": sql,
        "explanation": extra.get("explanation", "test query"),
        "tables_used": extra.get("tables_used", []),
        "assumptions": extra.get("assumptions", []),
        "clarification": None,
    }


UNANSWERABLE = {
    "answerable": False, "sql": None, "explanation": "", "tables_used": [], "assumptions": [],
    "clarification": "The schema has no information about weather.",
}


class ScriptedProvider(LLMProvider):
    """Returns queued JSON replies; records every prompt it receives.

    Queue items may be: a dict (returned as structured data), None (malformed
    output), or an Exception instance (raised).
    """

    name = "scripted"

    def __init__(self, replies: list[Any] | None = None, *, model: str = "claude-sonnet-5-5",
                 tokens: tuple[int | None, int | None] = (1000, 200), answer: str | None = None):
        self.model = model
        self.replies = deque(replies or [])
        self.tokens = tokens
        self.answer = answer
        self.prompts: list[tuple[str, str]] = []  # (purpose, prompt)

    def queue(self, *replies: Any) -> None:
        self.replies.extend(replies)

    def generate_json(self, system, prompt, json_schema, *, purpose):
        self.prompts.append((purpose, prompt))
        if not self.replies:
            raise AssertionError("ScriptedProvider ran out of replies")
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        return LLMResult(reply, str(reply), self.tokens[0], self.tokens[1], 5.0, self.model, purpose)

    def generate_text(self, system, prompt, *, purpose):
        self.prompts.append((purpose, prompt))
        if self.answer is None:
            raise LLMProviderError("no answer scripted")
        return LLMResult(None, self.answer, 300, 50, 3.0, self.model, purpose)
