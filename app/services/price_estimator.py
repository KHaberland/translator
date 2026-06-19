from math import ceil
from typing import Protocol


class PriceSettings(Protocol):
    openai_input_price_per_1m_tokens: float
    openai_output_price_per_1m_tokens: float


def estimate_output_tokens(input_tokens: int, multiplier: float) -> int:
    if input_tokens <= 0:
        return 0
    return max(1, ceil(input_tokens * multiplier))


def estimate_translation_cost_usd(
    input_tokens: int,
    output_tokens: int,
    settings: PriceSettings,
) -> float:
    input_cost = (
        input_tokens / 1_000_000 * settings.openai_input_price_per_1m_tokens
    )
    output_cost = (
        output_tokens / 1_000_000 * settings.openai_output_price_per_1m_tokens
    )
    return round(input_cost + output_cost, 6)


def budget_status(cost: float, budget: float) -> str:
    return "exceeded" if cost > budget else "ok"
