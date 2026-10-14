"""Model prices used for cost **estimates** (not invoice amounts).

Source: OpenAI pricing documentation, checked 2026-10-15. Update `PRICES_AS_OF` with any change.
A model without a price entry is refused (AI_NOT_CONFIGURED) so spend is never untracked.
"""

from dataclasses import dataclass
from decimal import Decimal

PRICES_AS_OF = "2026-10-15"
PER_TOKENS = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input_per_1m: Decimal
    cached_input_per_1m: Decimal
    output_per_1m: Decimal


PRICES: dict[str, ModelPrice] = {
    "gpt-4o-mini": ModelPrice(Decimal("0.15"), Decimal("0.075"), Decimal("0.60")),
    "text-embedding-3-small": ModelPrice(Decimal("0.02"), Decimal("0.02"), Decimal("0")),
    # Deterministic test doubles: never billed.
    "fake": ModelPrice(Decimal("0"), Decimal("0"), Decimal("0")),
}


def has_price(model: str) -> bool:
    return model in PRICES


def estimate_cost(
    model: str, input_tokens: int, output_tokens: int = 0, cached_tokens: int = 0
) -> Decimal:
    """`cached_tokens` is the cached subset of `input_tokens` (as reported by OpenAI)."""
    price = PRICES[model]
    cached = min(max(cached_tokens, 0), input_tokens)
    cost = (
        Decimal(input_tokens - cached) * price.input_per_1m
        + Decimal(cached) * price.cached_input_per_1m
        + Decimal(output_tokens) * price.output_per_1m
    ) / PER_TOKENS
    return cost.quantize(Decimal("0.00000001"))
