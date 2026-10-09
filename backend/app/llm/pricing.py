"""Cost estimation.

Prices are USD per 1M tokens and are *configuration, not truth*: provider prices change.
Only the mock provider has a built-in notional rate (so the dashboard has numbers to show
offline); for real models the rate must be supplied via LLM_PRICE_INPUT_PER_MTOK /
LLM_PRICE_OUTPUT_PER_MTOK, otherwise cost is reported as unknown (None), never guessed.
"""
from __future__ import annotations

from ..config import Settings, get_settings

# (input, output) USD per 1M tokens. The mock rate is NOTIONAL: a round placeholder in the
# range of small hosted models, used so offline eval runs can exercise the cost pipeline.
NOTIONAL_RATES = {"mock": (0.15, 0.60)}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int,
                  settings: Settings | None = None) -> float | None:
    s = settings or get_settings()
    if s.llm_price_input_per_mtok is not None and s.llm_price_output_per_mtok is not None:
        rin, rout = s.llm_price_input_per_mtok, s.llm_price_output_per_mtok
    elif provider in NOTIONAL_RATES:
        rin, rout = NOTIONAL_RATES[provider]
    else:
        return None
    return round((input_tokens * rin + output_tokens * rout) / 1_000_000, 8)
