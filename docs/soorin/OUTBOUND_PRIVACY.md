# Outbound model privacy boundary

The Python Chat health, embedding, and HTTP reranker adapters share `OutboundDataPolicy`. This is an offline/evaluation boundary; production Chat and embedding authority remains the Utopia Rust runtime.

The policy has two endpoint trust classes:

- `external` (default): non-sensitive text may pass; text classified as sensitive requires a successful injected `route_verifier` that returns an auditable attestation ID. There is no caller-provided `approved` boolean.
- `local_trusted`: an operator-declared endpoint inside the trusted deployment boundary. This classification must come from deployment configuration and network controls, not request content.

`block_all` takes precedence over every other condition. `block_sensitive` is the only other mode; the former unrestricted `allow` mode was removed. A request marked synthetic is accepted only when the policy was constructed with `test_mode=True`. Setting `synthetic=True` is not itself proof and is denied outside test mode.

Configuration uses `SOORIN_OUTBOUND_PRIVACY_MODE`, `SOORIN_OUTBOUND_ENDPOINT_TRUST`, and `SOORIN_OUTBOUND_TEST_MODE`. `SOORIN_SYNTHETIC_MODE` only labels requests and cannot enable test mode. The removed `SOORIN_OUTBOUND_PRIVACY_ROUTE_APPROVED` setting is intentionally ignored.

Audit decisions contain purpose, classification, item count, endpoint trust, optional attestation ID, and a SHA-256 content fingerprint. They do not contain request text. HTTP authentication/provider failures report a typed code and status only; provider response bodies are not copied into errors.

The built-in pattern classifier is a conservative guard, not a DLP product. A deployment that sends real SOC content to an external service must inject a trusted gateway verifier at the egress boundary and validate that the attestation covers the exact fingerprint. No such production gateway integration is claimed in Sprint 1.
