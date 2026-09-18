"""Shared catalog record validation helpers.

Extracted in S3 from the private helpers `backend/catalog/pitch.py` reached into,
so the demo importer and both catalog loaders validate identically.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


class CatalogValidationError(ValueError):
    """Raised when a catalog record cannot safely enter the application."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}")


def required_string(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CatalogValidationError(f"{field} must be a non-empty string")
    return value


def identifier(record: dict[str, Any], field: str) -> str:
    value = required_string(record, field)
    if not _IDENTIFIER.fullmatch(value):
        raise CatalogValidationError(f"{field} must be a safe identifier")
    return value


def parse_price(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise CatalogValidationError("price must be decimal-compatible") from error
    if not price.is_finite() or price < 0:
        raise CatalogValidationError("price must be finite and nonnegative")
    return price
