from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DecisionStatus(str, Enum):
    INSUFFICIENT = "insufficient"
    WATCH = "watch"
    PROBE = "probe"
    RECOMMEND = "recommend"


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    description: str


@dataclass(frozen=True)
class OperationalRecommendation:
    question: str
    scope: str
    status: DecisionStatus
    proposed_action: str | None
    support: tuple[EvidenceReference, ...]
    limitations: tuple[str, ...]
    next_probe: str | None = None
