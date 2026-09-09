"""Narrow, visible deterministic price interpretation. No model is involved."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

PRICE = re.compile(
    r"\b(under|less than|below|up to|at most|max(?:imum)?|over|more than|above|at least)\s*\$?\s*(\d+(?:\.\d{1,2})?)(?![\d.,])\b",
    re.IGNORECASE,
)
RANGE = re.compile(
    r"\bbetween\s*\$?(\d+(?:\.\d{1,2})?)\s+and\s*\$?(\d+(?:\.\d{1,2})?)(?![\d.,])\b", re.I
)
SORT = re.compile(r"\b(cheapest|lowest price|most expensive|highest price)\b", re.I)


@dataclass(frozen=True)
class QueryPlan:
    original: str
    visual: str
    maximum: Decimal | None
    inclusive: bool
    minimum: Decimal | None = None
    minimum_inclusive: bool = True
    sort: Literal["relevance", "price_asc", "price_desc"] = "relevance"

    def accepts(self, price: Decimal | None) -> bool:
        if self.maximum is None and self.minimum is None and self.sort == "relevance":
            return True
        return (
            price is not None
            and (
                self.maximum is None
                or (price <= self.maximum if self.inclusive else price < self.maximum)
            )
            and (
                self.minimum is None
                or (price >= self.minimum if self.minimum_inclusive else price > self.minimum)
            )
        )

    def label(self) -> str:
        parts = []
        if self.minimum is not None:
            parts.append(f"{'At least' if self.minimum_inclusive else 'Over'} ${self.minimum}")
        if self.maximum is not None:
            parts.append(f"{'Up to' if self.inclusive else 'Under'} ${self.maximum}")
        if self.sort != "relevance":
            parts.append(
                "Lowest price first" if self.sort == "price_asc" else "Highest price first"
            )
            if self.visual:
                parts.append("among 12 closest matches")
        return " · ".join(parts) + (" · illustrative prices" if parts else "")

    def filters(self) -> dict[str, object]:
        filters: dict[str, object] = {}
        if self.maximum is not None:
            filters.update(price_max=str(self.maximum), inclusive=self.inclusive)
        if self.minimum is not None:
            filters.update(price_min=str(self.minimum), minimum_inclusive=self.minimum_inclusive)
        if self.sort != "relevance":
            filters.update(sort=self.sort, semantic_candidate_limit=12 if self.visual else None)
        return filters


def parse_price(text: str) -> QueryPlan:
    # Keep the existing entry point for UI/telemetry callers; now returns a query plan.
    maximum, minimum, inclusive, minimum_inclusive = None, None, True, True
    visual = text
    for match in RANGE.finditer(text):
        lower, upper = Decimal(match[1]), Decimal(match[2])
        if lower > upper:
            raise ValueError("price range minimum exceeds maximum")
        minimum = lower if minimum is None else max(minimum, lower)
        maximum = upper if maximum is None else min(maximum, upper)
    visual = RANGE.sub("", visual)
    for match in PRICE.finditer(visual):
        amount = Decimal(match[2])
        operator = match[1].lower()
        if operator in ("over", "more than", "above", "at least"):
            bound_inclusive = operator == "at least"
            if minimum is None or amount > minimum:
                minimum, minimum_inclusive = amount, bound_inclusive
            elif amount == minimum:
                minimum_inclusive = minimum_inclusive and bound_inclusive
        else:
            bound_inclusive = operator in ("up to", "at most", "max", "maximum")
            if maximum is None or amount < maximum:
                maximum, inclusive = amount, bound_inclusive
            elif amount == maximum:
                inclusive = inclusive and bound_inclusive
    visual = PRICE.sub("", visual)
    orderings = {
        "price_asc" if m[1].lower() in ("cheapest", "lowest price") else "price_desc"
        for m in SORT.finditer(visual)
    }
    if len(orderings) > 1:
        raise ValueError("choose one price ordering")
    sort: Literal["relevance", "price_asc", "price_desc"] = "relevance"
    if orderings:
        sort = "price_asc" if "price_asc" in orderings else "price_desc"
    visual = " ".join(SORT.sub("", visual).split())
    if sort != "relevance" and visual.lower() in ("", "one", "ones", "item", "items"):
        visual = ""
    return QueryPlan(text, visual, maximum, inclusive, minimum, minimum_inclusive, sort)
