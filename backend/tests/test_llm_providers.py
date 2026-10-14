"""Provider + parsing tests. HTTP is faked with httpx.MockTransport - no network."""

import json

import httpx
import pytest

from app.core.errors import LLMProviderError, LLMResponseParseError
from app.services.answer_service import AnswerService, template_answer
from app.services.llm_service import AnthropicProvider, MockProvider, OpenAICompatibleProvider
from app.services.query_executor import ColumnInfo, ExecutionResult
from app.services.sql_generator import GENERATION_SCHEMA, parse_generation
from tests.fakes import ScriptedProvider


def test_parse_strips_markdown_fences_and_semicolon():
    parsed = parse_generation({
        "answerable": True, "sql": "```sql\nSELECT 1;\n```", "explanation": "x",
        "tables_used": [], "assumptions": [], "clarification": None,
    })
    assert parsed.sql == "SELECT 1"


@pytest.mark.parametrize("data", [None, "SELECT 1", {"answerable": True, "sql": ""},
                                  {"answerable": "maybe"}])
def test_parse_rejects_malformed_responses(data):
    with pytest.raises(LLMResponseParseError):
        parse_generation(data)


def test_parse_accepts_unanswerable():
    parsed = parse_generation({"answerable": False, "sql": None, "clarification": "no data"})
    assert parsed.answerable is False and parsed.clarification == "no data"


def anthropic_with(handler):
    client = httpx.Client(base_url="https://api.anthropic.com", transport=httpx.MockTransport(handler),
                          headers={"x-api-key": "sk-test-secret", "anthropic-version": "2023-06-01"})
    return AnthropicProvider("sk-test-secret", "claude-sonnet-5-5", "", 5, 512, client=client)


def test_anthropic_forced_tool_use_and_usage():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx.Response(200, json={
            "model": "claude-sonnet-5-5",
            "content": [{"type": "tool_use", "name": "submit_sql",
                         "input": {"answerable": True, "sql": "SELECT 1", "explanation": "e",
                                   "tables_used": [], "assumptions": [], "clarification": None}}],
            "usage": {"input_tokens": 812, "output_tokens": 95},
        })

    result = anthropic_with(handler).generate_json("sys", "prompt", GENERATION_SCHEMA, purpose="generation")
    assert result.data["sql"] == "SELECT 1"
    assert (result.input_tokens, result.output_tokens) == (812, 95)
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "submit_sql"}
    assert seen["body"]["tools"][0]["input_schema"] == GENERATION_SCHEMA
    assert seen["headers"]["anthropic-version"] == "2023-06-01"


def test_anthropic_missing_tool_block_keeps_usage():
    provider = anthropic_with(lambda r: httpx.Response(200, json={
        "content": [{"type": "text", "text": "sorry"}], "usage": {"input_tokens": 5, "output_tokens": 2}}))
    result = provider.generate_json("s", "p", GENERATION_SCHEMA, purpose="generation")
    assert result.data is None and result.input_tokens == 5


def test_anthropic_auth_error_is_safe():
    provider = anthropic_with(lambda r: httpx.Response(401, json={"error": {"message": "bad key sk-test-secret"}}))
    with pytest.raises(LLMProviderError) as exc:
        provider.generate_json("s", "p", GENERATION_SCHEMA, purpose="generation")
    assert "401" in exc.value.message
    assert "sk-test-secret" not in exc.value.message


def test_openai_compatible_json_mode():
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={
            "model": "gpt-x",
            "choices": [{"message": {"content": json.dumps({"answerable": True, "sql": "SELECT 2"})}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        })

    client = httpx.Client(base_url="https://x/v1", transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider("k", "gpt-x", "", 5, 512, client=client)
    result = provider.generate_json("s", "p", GENERATION_SCHEMA, purpose="generation")
    assert result.data["sql"] == "SELECT 2" and result.input_tokens == 100


@pytest.mark.parametrize(
    "question",
    [
        "How many units of each product category were sold in completed orders?",  # units + status
        "What was our total revenue in 2025?",                                     # date range
        "Top 3 products by revenue among enterprise customers",                    # segment
        "Which product categories perform best in India?",                         # location
    ],
)
def test_mock_refuses_constraints_it_cannot_apply(question):
    """Precision over coverage: never answer a different question than was asked."""
    data = MockProvider._answer(question.lower())
    assert data["answerable"] is False and "won't guess" in data["clarification"]


def test_mock_honours_requested_numbers():
    assert MockProvider._answer("show the top 3 products by revenue")["sql"].endswith("LIMIT 3")
    assert "LIMIT 5" in MockProvider._answer("the five customers who placed the most orders")["sql"]
    assert "'-2 months'" in MockProvider._answer("monthly revenue for the last 3 months")["sql"]


def test_mock_provider_reports_unknown_usage_and_is_labelled():
    provider = MockProvider()
    result = provider.generate_json("s", "<question>What is our total revenue?</question>", {},
                                    purpose="generation")
    assert result.data["answerable"] and "SUM" in result.data["sql"]
    assert result.input_tokens is None  # unavailable, never invented
    assert provider.is_real_llm is False
    other = provider.generate_json("s", "<question>favourite colour?</question>", {}, purpose="generation")
    assert other.data["answerable"] is False


def _execution(rows, cols=("n",)):
    return ExecutionResult([ColumnInfo(c, "number") for c in cols], rows, len(rows), False, 1.0)


def test_answer_for_empty_result_never_calls_llm():
    provider = ScriptedProvider(answer="should not be used")
    answer, call = AnswerService(provider, "llm", 20).answer("q", "SELECT", _execution([]))
    assert answer == "No matching records were found." and call is None
    assert provider.prompts == []


def test_llm_answer_receives_actual_rows():
    provider = ScriptedProvider(answer="Total revenue is $1,234.50.")
    answer, call = AnswerService(provider, "llm", 20).answer("q", "SELECT", _execution([[1234.5]]))
    assert answer == "Total revenue is $1,234.50." and call.input_tokens == 300
    assert "1234.5" in provider.prompts[0][1]


def test_answer_falls_back_to_template_when_llm_fails():
    provider = ScriptedProvider(answer=None)  # generate_text raises
    answer, call = AnswerService(provider, "llm", 20).answer("q", "SELECT", _execution([[42]]))
    assert answer == template_answer("q", _execution([[42]])) and call is None
