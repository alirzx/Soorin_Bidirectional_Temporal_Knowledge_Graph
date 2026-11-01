"""Optional NER enrichment interface.

No model is loaded by default. Implementations must return proposed entities;
callers validate and keep them separate from deterministic source identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class NerProposal:
    entity_type: str
    value: str
    score: float
    model_version: str


class NerProvider(Protocol):
    def extract(self, text: str) -> list[NerProposal]: ...


class DisabledNer:
    def extract(self, text: str) -> list[NerProposal]:
        return []
