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
    endpoint_trust: str
    route_attestation_id: str | None
    item_count: int
    content_fingerprint: str


AuditSink = Callable[[OutboundDecision], None]
RouteVerifier = Callable[[str, str], str | None]


@dataclass(slots=True)
class OutboundDataPolicy:
    mode: str = "block_sensitive"
    endpoint_trust: str = "external"
    test_mode: bool = False
    route_verifier: RouteVerifier | None = None
    audit_sink: AuditSink | None = None

    def evaluate(
        self, texts: Sequence[str], *, purpose: str, synthetic: bool = False,
    ) -> OutboundDecision:
        if self.mode not in {"block_sensitive", "block_all"}:
            raise OutboundPolicyError("invalid_privacy_mode", self.mode)
        if self.endpoint_trust not in {"external", "local_trusted"}:
            raise OutboundPolicyError("invalid_endpoint_trust", self.endpoint_trust)
        if not isinstance(purpose, str) or not purpose.strip():
            raise OutboundPolicyError("invalid_purpose", "purpose is required")
        if not texts or any(not isinstance(text, str) for text in texts):
            raise OutboundPolicyError("invalid_outbound_content", "texts must be a nonempty string sequence")
        joined = "\n".join(texts)
        fingerprint = hashlib.sha256(joined.encode("utf-8")).hexdigest()
        classification = "sensitive" if any(pattern.search(joined) for pattern in (IP_RE, EMAIL_RE, SECRET_RE, SOC_RE)) else "non_sensitive"
        attestation_id: str | None = None
        if self.mode == "block_all":
            allowed, reason = False, "external_outbound_disabled"
        elif synthetic and not self.test_mode:
            allowed, reason = False, "synthetic_requires_test_mode"
        elif self.endpoint_trust == "local_trusted":
            allowed, reason = True, "local_trusted_endpoint"
        elif synthetic:
            allowed, reason = True, "synthetic_test_data"
        elif classification == "sensitive":
            if self.route_verifier is not None:
                try:
                    attestation_id = self.route_verifier(purpose, fingerprint)
                except Exception:
                    attestation_id = None
            if isinstance(attestation_id, str) and attestation_id.strip():
                allowed, reason = True, "verified_privacy_route"
            else:
                allowed, reason = False, "sensitive_content_requires_verified_privacy_route"
        else:
            allowed, reason = True, "non_sensitive_content"
        decision = OutboundDecision(
            allowed, reason, classification, purpose, synthetic, self.endpoint_trust, attestation_id,
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
