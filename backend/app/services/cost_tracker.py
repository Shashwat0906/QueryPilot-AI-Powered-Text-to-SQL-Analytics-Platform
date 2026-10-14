"""Token usage and estimated cost.

cost = input_tokens / 1e6 * input_price + output_tokens / 1e6 * output_price

summed over EVERY LLM call in the request: initial generation, each
correction, and the answer summary.

Honesty rules:
* If any call did not report its token counts, or the model has no price in
  the pricing table, the cost is `None` ("unavailable") - not 0.
* A request that made no LLM calls (cache hit) genuinely cost $0, so its
  status is "no_llm_calls" with cost 0.0.
* All costs are labelled as *estimates*: they use list prices and ignore
  discounts such as prompt caching or batch pricing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.llm_service import LLMResult


@dataclass
class CostSummary:
    llm_calls: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    status: str  # "estimated" | "unavailable" | "no_llm_calls"
    note: str


def summarize_cost(calls: list[LLMResult], model: str, pricing: dict[str, dict[str, float]]) -> CostSummary:
    if not calls:
        return CostSummary(0, 0, 0, 0.0, "no_llm_calls", "No LLM calls were made.")

    if any(c.input_tokens is None or c.output_tokens is None for c in calls):
        return CostSummary(
            len(calls), None, None, None, "unavailable",
            "The provider did not report token usage, so cost cannot be estimated.",
        )

    tokens_in = sum(c.input_tokens or 0 for c in calls)
    tokens_out = sum(c.output_tokens or 0 for c in calls)
    price = pricing.get(model)
    if price is None:
        return CostSummary(
            len(calls), tokens_in, tokens_out, None, "unavailable",
            f"No price configured for model '{model}' (set MODEL_PRICING_JSON).",
        )
    cost = tokens_in / 1_000_000 * price["input"] + tokens_out / 1_000_000 * price["output"]
    return CostSummary(
        len(calls), tokens_in, tokens_out, round(cost, 6), "estimated",
        f"Estimate at list price: ${price['input']}/MTok input, ${price['output']}/MTok output.",
    )
