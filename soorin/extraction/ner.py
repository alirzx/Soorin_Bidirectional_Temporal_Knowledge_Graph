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
    source_label: str | None = None
    review_required: bool = True

    def __post_init__(self) -> None:
        for name in ("entity_type", "value", "model_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"NER proposal {name} must be a non-empty string")
        if isinstance(self.score, bool) or not isinstance(self.score, (float, int)):
            raise ValueError("NER proposal score must be numeric")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("NER proposal score must be in [0, 1]")
        if self.source_label is not None and not isinstance(self.source_label, str):
            raise ValueError("NER proposal source_label must be a string")
        if not isinstance(self.review_required, bool):
            raise ValueError("NER proposal review_required must be boolean")


class NerProvider(Protocol):
    def extract(self, text: str) -> list[NerProposal]: ...


class DisabledNer:
    def extract(self, text: str) -> list[NerProposal]:
        return []
