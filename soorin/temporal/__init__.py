"""SOC lifecycle and revision classification."""

from .lifecycle import LifecycleDecision, RevisionState, classify_revision

__all__ = ["LifecycleDecision", "RevisionState", "classify_revision"]
