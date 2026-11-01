"""Alert lifecycle classification mapped to Utopia's two temporal axes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from soorin.contracts.knowledge_event_v1 import canonical_json, normalize_timestamp
import hashlib


@dataclass(frozen=True, slots=True)
class RevisionState:
    source_record_id: str
    event_time: str
    recorded_at: str
    content_checksum: str
    status: str | None = None
    revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    kind: str
    create_revision: bool
    closes_previous: bool
    rationale: str


def checksum_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def classify_revision(
    previous: RevisionState | None,
    *, source_record_id: str,
    event_time: str,
    recorded_at: str,
    content_checksum: str,
    status: str | None = None,
    explicit_action: str | None = None,
) -> LifecycleDecision:
    event_time = normalize_timestamp(event_time, "event_time", required=True)
    recorded_at = normalize_timestamp(recorded_at, "recorded_at", required=True)
    if previous is None:
        return LifecycleDecision("new_occurrence", True, False, "first observation of this source identity")
    if previous.source_record_id != source_record_id:
        return LifecycleDecision("new_occurrence", True, False, "different authoritative source record")
    if previous.content_checksum == content_checksum:
        return LifecycleDecision("exact_replay", False, False, "canonical content checksum is unchanged")
    if explicit_action in {"retraction", "supersession"}:
        return LifecycleDecision(explicit_action, True, True, f"source explicitly declared {explicit_action}")
    if event_time < normalize_timestamp(previous.event_time, "previous.event_time", required=True):
        return LifecycleDecision("late_arrival", True, False, "event time predates the latest recorded revision")
    if status is not None and status != previous.status:
        return LifecycleDecision("state_change", True, True, "alert lifecycle status changed")
    return LifecycleDecision("correction", True, True, "same source identity changed without a lifecycle transition")


def utopia_temporal_mapping(state: RevisionState) -> dict[str, str | None]:
    """Expose the explicit mapping used by the Statements adapter.

    ``event_time`` maps to world/valid time; ``recorded_at`` maps to the
    knowledge axis. Utopia owns ``invalidated_at`` when a pushed document is
    replaced, so callers must not fabricate it in the open Statements payload.
    """

    return {
        "valid_from": normalize_timestamp(state.event_time, "event_time", required=True),
        "recorded_at": normalize_timestamp(state.recorded_at, "recorded_at", required=True),
        "invalidated_at": None,
    }
