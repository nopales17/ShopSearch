"""Narrow, visible deterministic price interpretation. No model is involved."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

PRICE = re.compile(
    r"\b(under|less than|below|up to|at most|max(?:imum)?)\s*\$?\s*(\d+(?:\.\d{1,2})?)(?![\d.])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PriceQuery:
    original: str
    visual: str
    maximum: Decimal | None
    inclusive: bool

    def accepts(self, price: Decimal | None) -> bool:
        if self.maximum is None:
            return True
        return price is not None and (
            price <= self.maximum if self.inclusive else price < self.maximum
        )

    def filters(self) -> dict[str, object]:
        return (
            {}
            if self.maximum is None
            else {"price_max": str(self.maximum), "inclusive": self.inclusive}
        )


def parse_price(text: str) -> PriceQuery:
    matches = list(PRICE.finditer(text))
    maximum, inclusive = None, True
    for match in matches:
        amount = Decimal(match[2])
        bound_inclusive = match[1].lower() in ("up to", "at most", "max", "maximum")
        if maximum is None or amount < maximum:
            maximum, inclusive = amount, bound_inclusive
        elif amount == maximum:
            inclusive = inclusive and bound_inclusive
    visual = " ".join(PRICE.sub("", text).split())
    return PriceQuery(text, visual, maximum, inclusive)
