"""Auditable, content-free decisions for outbound model requests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Callable, Sequence

IP_RE = re.compile(r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SECRET_RE = re.compile(r"\b(?:api[_ -]?key|bearer|password|secret|token)\b", re.IGNORECASE)
SOC_RE = re.compile(r"\b(?:alert|notable|incident|powershell|malware|authentication failures?|source event)\b", re.IGNORECASE)


class OutboundPolicyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class OutboundDecision:
    allowed: bool
    reason: str
    classification: str
    purpose: str
    synthetic: bool
    approved_privacy_route: bool
    item_count: int
    content_fingerprint: str


AuditSink = Callable[[OutboundDecision], None]


@dataclass(slots=True)
class OutboundDataPolicy:
    mode: str = "block_sensitive"
    allow_synthetic: bool = True
    audit_sink: AuditSink | None = None

    def evaluate(
        self, texts: Sequence[str], *, purpose: str, synthetic: bool = False,
        approved_privacy_route: bool = False,
    ) -> OutboundDecision:
        if self.mode not in {"block_sensitive", "block_all", "allow"}:
            raise OutboundPolicyError("invalid_privacy_mode", self.mode)
        joined = "\n".join(texts)
        fingerprint = hashlib.sha256(joined.encode("utf-8")).hexdigest()
        classification = "sensitive" if any(pattern.search(joined) for pattern in (IP_RE, EMAIL_RE, SECRET_RE, SOC_RE)) else "non_sensitive"
        if approved_privacy_route:
            allowed, reason = True, "approved_privacy_route"
        elif synthetic and self.allow_synthetic:
            allowed, reason = True, "synthetic_test_data"
        elif self.mode == "allow":
            allowed, reason = True, "explicit_allow_mode"
        elif self.mode == "block_all":
            allowed, reason = False, "external_outbound_disabled"
        elif classification == "sensitive":
            allowed, reason = False, "sensitive_content_requires_privacy_route"
        else:
            allowed, reason = True, "non_sensitive_content"
        decision = OutboundDecision(
            allowed, reason, classification, purpose, synthetic, approved_privacy_route,
            len(texts), fingerprint,
        )
        if self.audit_sink:
            self.audit_sink(decision)
        return decision

    def require_allowed(self, texts: Sequence[str], **context: object) -> OutboundDecision:
        decision = self.evaluate(texts, **context)  # type: ignore[arg-type]
        if not decision.allowed:
            raise OutboundPolicyError("privacy_blocked", decision.reason)
        return decision
