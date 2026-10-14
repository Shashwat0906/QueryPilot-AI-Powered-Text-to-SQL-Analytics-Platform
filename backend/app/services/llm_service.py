"""LLM provider abstraction.

Every provider implements the same two methods:

* `generate_json(system, prompt, json_schema)` - structured output (used for SQL)
* `generate_text(system, prompt)`               - free text (used for answers)

and reports token usage on every call. The rest of the app depends only on
`LLMProvider`, so swapping Claude for another provider is a config change.

Providers:
* `AnthropicProvider` - Claude Messages API over HTTPX. Structured output is
  obtained with *forced tool use*: we define one tool whose input schema is
  our JSON schema and require the model to call it, so the reply is already
  parsed, schema-shaped JSON.
* `OpenAICompatibleProvider` - any /chat/completions endpoint with JSON mode.
* `MockProvider` - offline, deterministic, pattern-matched SQL for the demo
  questions. It is NOT an LLM; the UI labels it clearly. Its token usage is
  reported as unavailable (None), never as zero.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import LLMProviderError, LLMResponseParseError
from app.services.result_checks import NUMBER_WORDS, requested_row_count


@dataclass
class LLMResult:
    """One LLM call: its output plus measured usage."""

    data: dict[str, Any] | None
    text: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float
    model: str
    purpose: str = "generation"  # generation | correction | answer


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def generate_json(
        self, system: str, prompt: str, json_schema: dict[str, Any], *, purpose: str
    ) -> LLMResult: ...

    @abstractmethod
    def generate_text(self, system: str, prompt: str, *, purpose: str) -> LLMResult: ...

    @property
    def is_real_llm(self) -> bool:
        return True


def _safe_provider_error(provider: str, exc: Exception) -> LLMProviderError:
    """Turn HTTP/network errors into a message that leaks nothing sensitive."""

    if isinstance(exc, httpx.TimeoutException):
        return LLMProviderError(f"The {provider} API timed out.")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        hint = {
            401: "authentication failed - check the API key",
            403: "access denied for this key",
            404: "model or endpoint not found - check the model name",
            429: "rate limit or quota exceeded",
        }.get(status, "the provider returned an error")
        return LLMProviderError(f"The {provider} API returned HTTP {status}: {hint}.")
    return LLMProviderError(f"Could not reach the {provider} API.")


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float, max_tokens: int,
                 client: httpx.Client | None = None):
        self.model = model
        self._max_tokens = max_tokens
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json",
            },
        )

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        started = time.perf_counter()
        try:
            response = self._client.post("/v1/messages", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise _safe_provider_error("Anthropic", exc) from None
        return response.json(), (time.perf_counter() - started) * 1000

    @staticmethod
    def _usage(body: dict[str, Any]) -> tuple[int | None, int | None]:
        usage = body.get("usage") or {}
        return usage.get("input_tokens"), usage.get("output_tokens")

    def generate_json(self, system, prompt, json_schema, *, purpose):
        payload = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{
                "name": "submit_sql",
                "description": "Submit the SQL query and metadata answering the question.",
                "input_schema": json_schema,
            }],
            "tool_choice": {"type": "tool", "name": "submit_sql"},
        }
        body, latency = self._post(payload)
        tokens_in, tokens_out = self._usage(body)
        block = next((b for b in body.get("content", []) if b.get("type") == "tool_use"), None)
        # A missing / malformed block gives data=None; `parse_generation` then
        # raises a parse error, but the tokens of this call are still counted.
        data = block.get("input") if block and isinstance(block.get("input"), dict) else None
        return LLMResult(data, json.dumps(data), tokens_in, tokens_out,
                         latency, body.get("model", self.model), purpose)

    def generate_text(self, system, prompt, *, purpose):
        payload = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        body, latency = self._post(payload)
        tokens_in, tokens_out = self._usage(body)
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        return LLMResult(None, text.strip(), tokens_in, tokens_out, latency,
                         body.get("model", self.model), purpose)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float, max_tokens: int,
                 client: httpx.Client | None = None):
        self.model = model
        self._max_tokens = max_tokens
        self._client = client or httpx.Client(
            base_url=base_url, timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def _chat(self, system: str, prompt: str, json_mode: bool) -> tuple[dict[str, Any], float]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise _safe_provider_error("OpenAI-compatible", exc) from None
        return response.json(), (time.perf_counter() - started) * 1000

    def generate_json(self, system, prompt, json_schema, *, purpose):
        instructions = (
            f"{system}\n\nRespond with a single JSON object matching this JSON schema:\n"
            f"{json.dumps(json_schema)}"
        )
        body, latency = self._chat(instructions, prompt, json_mode=True)
        usage = body.get("usage") or {}
        content = ""
        try:
            content = body["choices"][0]["message"]["content"] or ""
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            data = None  # parse_generation reports it; usage is still counted
        return LLMResult(data, content, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                         latency, body.get("model", self.model), purpose)

    def generate_text(self, system, prompt, *, purpose):
        body, latency = self._chat(system, prompt, json_mode=False)
        usage = body.get("usage") or {}
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMResponseParseError("The model returned an empty response.") from None
        return LLMResult(None, text.strip(), usage.get("prompt_tokens"),
                         usage.get("completion_tokens"), latency, body.get("model", self.model),
                         purpose)


_REVENUE = "oi.quantity * oi.unit_price * (1 - oi.discount)"
_VALID = "o.status NOT IN ('cancelled', 'refunded')"

# Constraints the mock can recognise in a question. If a question contains a
# constraint that the matched rule cannot apply, the mock refuses instead of
# answering a different question (the bug behind "ran but wrong" results).
_CONSTRAINTS: dict[str, re.Pattern[str]] = {
    "order status": re.compile(r"\b(completed|shipped|pending|cancell?ed|refund(?:ed|s)?|returned)\b", re.I),
    "date range": re.compile(
        r"\b(?:19|20)\d\d\b|\b(?:january|february|march|april|may|june|july|august|september|"
        r"october|november|december|today|yesterday|week|quarter|year|ytd)\b", re.I),
    "payment method": re.compile(r"\b(?:card|upi|paypal|bank|payment)\b", re.I),
    "customer segment": re.compile(r"\b(?:segment|consumer|enterprise|small business)\b", re.I),
    "location": re.compile(r"\b(?:city|cities|country|countries|state|region|india|usa|uk|canada|germany)\b", re.I),
    "units measure": re.compile(r"\b(?:units?|quantity|quantities|volume)\b", re.I),
    "profit measure": re.compile(r"\b(?:profit|margin|cost)\b", re.I),
}


def _months(question: str) -> int | None:
    m = re.search(r"\b(?:last|past|previous)\s+(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")\s+months?\b",
                  question, re.I)
    if not m:
        return None
    token = m.group(1).lower()
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


def _rule_never_ordered(q: str) -> tuple[str, str, list[str], list[str]] | None:
    if not re.search(r"\bnever\b.*\bordered\b|\bnot been ordered\b", q):
        return None
    return ("SELECT p.product_id, p.name, p.category FROM products p "
            "WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id) "
            "ORDER BY p.name",
            "Products with no matching order_items rows.", ["products", "order_items"], [])


def _rule_monthly_revenue(q: str):
    if not re.search(r"\bmonthly\b|\bper month\b|\bby month\b", q) or "revenue" not in q:
        return None
    months = _months(q)
    where = _VALID
    assumptions = []
    if months:
        where += f" AND o.order_date >= date('{_REFERENCE_DATE}', 'start of month', '-{months - 1} months')"
        assumptions.append(f"Last {months} calendar months up to the data reference date.")
    return (f"SELECT strftime('%Y-%m', o.order_date) AS month, ROUND(SUM({_REVENUE}), 2) AS revenue "
            f"FROM orders o JOIN order_items oi ON oi.order_id = o.order_id WHERE {where} "
            "GROUP BY month ORDER BY month",
            "Revenue per month.", ["orders", "order_items"], assumptions)


def _rule_category_revenue(q: str):
    if "categor" not in q:
        return None
    return (f"SELECT p.category, ROUND(SUM({_REVENUE}), 2) AS revenue "
            f"FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
            f"JOIN orders o ON o.order_id = oi.order_id WHERE {_VALID} "
            "GROUP BY p.category ORDER BY revenue DESC",
            "Revenue per product category, best first.", ["order_items", "products", "orders"],
            ["'Perform best' interpreted as highest revenue."])


def _rule_top_products(q: str):
    if "product" not in q or "revenue" not in q:
        return None
    n = requested_row_count(q) or 5
    return (f"SELECT p.product_id, p.name, ROUND(SUM({_REVENUE}), 2) AS revenue FROM order_items oi "
            f"JOIN products p ON p.product_id = oi.product_id JOIN orders o ON o.order_id = oi.order_id "
            f"WHERE {_VALID} GROUP BY p.product_id, p.name ORDER BY revenue DESC LIMIT {n}",
            f"Top {n} products ranked by revenue.", ["order_items", "products", "orders"],
            [] if requested_row_count(q) else ["No number given; showing the top 5."])


def _rule_top_customers(q: str):
    if "customer" not in q or "order" not in q or not re.search(r"\bmost\b", q):
        return None
    n = requested_row_count(q) or 10
    return ("SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer, "
            "COUNT(o.order_id) AS order_count "
            "FROM customers c JOIN orders o ON o.customer_id = c.customer_id "
            f"GROUP BY c.customer_id ORDER BY order_count DESC, customer LIMIT {n}",
            f"Top {n} customers by number of orders placed (any status).", ["customers", "orders"],
            ["Counts every order the customer placed, including cancelled ones."])


def _rule_average_order_value(q: str):
    if not re.search(r"\baverage order value\b|\baov\b", q):
        return None
    return (f"SELECT ROUND(SUM({_REVENUE}) / COUNT(DISTINCT o.order_id), 2) AS average_order_value "
            f"FROM orders o JOIN order_items oi ON oi.order_id = o.order_id WHERE {_VALID}",
            "Revenue divided by the number of revenue-counting orders.", ["orders", "order_items"], [])


def _rule_total_revenue(q: str):
    if not re.search(r"\btotal revenue\b", q):
        return None
    return (f"SELECT ROUND(SUM({_REVENUE}), 2) AS total_revenue FROM orders o "
            f"JOIN order_items oi ON oi.order_id = o.order_id WHERE {_VALID}",
            "Sum of line revenue over non-cancelled, non-refunded orders.", ["orders", "order_items"], [])


_REFERENCE_DATE = "2026-09-29"
# Order matters: more specific rules first. Each rule lists the constraint
# kinds it can actually apply; anything else in the question means "refuse".
_MOCK_RULES = [
    (_rule_never_ordered, set()),
    (_rule_monthly_revenue, set()),  # "last N months" is parsed by the rule itself
    (_rule_category_revenue, set()),
    (_rule_top_products, set()),
    (_rule_top_customers, set()),
    (_rule_average_order_value, set()),
    (_rule_total_revenue, set()),
]


def _unanswerable(reason: str) -> dict:
    return {"answerable": False, "sql": None, "explanation": "", "tables_used": [],
            "assumptions": [], "clarification": reason}


class MockProvider(LLMProvider):
    """Offline stand-in used when no API key is configured (and by the demo).

    It recognises the built-in example questions with small hand-written
    rules and returns correct SQL for each. The SQL still goes through
    validation and really runs against the database, so the *results* are
    real - only the SQL generation is pre-written.

    Precision over coverage: if the question contains a constraint the rule
    can't apply (a status, a date range, a different measure, ...), the mock
    says it can't answer rather than returning an answer to a different
    question. It is NOT an LLM; anything outside its rules is unanswerable.
    """

    name = "mock"
    model = "mock-rules-v2"

    @property
    def is_real_llm(self) -> bool:
        return False

    def generate_json(self, system, prompt, json_schema, *, purpose):
        started = time.perf_counter()
        match = re.search(r"<question>(.*?)</question>", prompt, re.S)
        question = (match.group(1) if match else prompt).lower()
        data = self._answer(question)
        return LLMResult(data, json.dumps(data), None, None,
                         (time.perf_counter() - started) * 1000, self.model, purpose)

    @staticmethod
    def _answer(question: str) -> dict:
        # Remove phrases a rule parses itself so they aren't mistaken for constraints.
        stripped = re.sub(r"\b(?:last|past|previous)\s+\w+\s+months?\b", " ", question)
        for rule, handles in _MOCK_RULES:
            found = rule(question)
            if found is None:
                continue
            unsupported = [name for name, pattern in _CONSTRAINTS.items()
                           if name not in handles and pattern.search(stripped)]
            if unsupported:
                return _unanswerable(
                    "The offline mock provider recognised this question but can't apply its "
                    f"{', '.join(unsupported)} condition, so it won't guess. Set ANTHROPIC_API_KEY "
                    "to use Claude for any question.")
            sql, explanation, tables, assumptions = found
            return {"answerable": True, "sql": sql, "explanation": explanation,
                    "tables_used": tables, "assumptions": ["Pre-written mock query.", *assumptions],
                    "clarification": None}
        return _unanswerable(
            "The offline mock provider only knows the built-in example questions. "
            "Set ANTHROPIC_API_KEY to use Claude for any question.")

    def generate_text(self, system, prompt, *, purpose):
        raise LLMProviderError("The mock provider cannot write free-text answers.")


def build_provider(settings: Settings) -> LLMProvider:
    provider = settings.resolved_provider
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMProviderError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.")
        return AnthropicProvider(
            settings.anthropic_api_key.get_secret_value(), settings.anthropic_model,
            settings.anthropic_base_url, settings.llm_timeout_seconds, settings.llm_max_output_tokens,
        )
    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMProviderError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        return OpenAICompatibleProvider(
            settings.openai_api_key.get_secret_value(), settings.openai_model,
            settings.openai_base_url, settings.llm_timeout_seconds, settings.llm_max_output_tokens,
        )
    return MockProvider()
