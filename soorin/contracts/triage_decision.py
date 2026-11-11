"""Agentic-compatible attributed decisions; no response execution or fact promotion."""
from dataclasses import dataclass, asdict
import math
from .knowledge_event_v1 import normalize_timestamp

VERDICTS = frozenset({"true_positive", "benign_true_positive", "false_positive", "benign", "needs_review"})


@dataclass(frozen=True)
class TriageDecision:
    decision_id: str
    tenant_id: str
    alert_id: str
    investigation_run_id: str
    agent_id: str
    verdict: str
    confidence: float
    confidence_semantics: str
    evidence_ids: tuple[str, ...]
    decided_at: str
    model_version: str
    revision: int = 1
    review_status: str = "pending"
    human_override: str | None = None
    schema_version: str = "soorin.triage-decision.v1"

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError("unsupported triage verdict")
        if isinstance(self.confidence, bool) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be finite in [0,1]")
        if not self.confidence_semantics.strip() or self.revision < 1:
            raise ValueError("confidence semantics and positive revision required")
        for name in ("decision_id", "tenant_id", "alert_id", "investigation_run_id", "agent_id", "model_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        if self.review_status not in {"pending", "approved", "rejected", "overridden"}:
            raise ValueError("unsupported review status")
        if self.human_override is not None and self.human_override not in VERDICTS:
            raise ValueError("invalid override verdict")
        object.__setattr__(self, "decided_at", normalize_timestamp(self.decided_at, "decided_at", required=True))

    def to_dict(self):
        return asdict(self)
