# Deterministic entity resolution

`soorin/identity/` normalizes Unicode NFKC text, IDNA hostnames, compressed IPv4/IPv6, Windows principals, UPNs, and MITRE IDs. Canonical keys hash a deterministic JSON identity tuple.

## Automatic identity

Automatic resolution requires tenant scope plus a trusted source identifier. Depending on type, the tuple also includes source system, source instance, directory/network scope, and authoritative ID. Hostnames, aliases, private IPs, and embedding similarity alone never trigger automatic merges.

Examples:

- A CMDB `asset_id` survives host rename; old/new hostnames remain temporal aliases.
- The same hostname in two tenants produces different keys.
- `10.0.0.1` without network scope is ambiguous. Different VPC/network scopes produce different keys.
- `DOMAIN\\user` and UPNs are normalized but remain provisional without an authoritative directory object ID.
- Conflicting authoritative IDs create separate entities and a review candidate, not an automatic merge.

`IdentityDecision` records `resolved`, `provisional`, or `ambiguous`, automatic status, rationale, aliases, and candidate keys. Semantic similarity is permitted only to discover candidates for an explicit merge/split decision.

No database migration was added in Sprint 1: deterministic keys fit the existing Statements identity flow. A later persistent registry should be Soorin-owned, tenant-unique, transactional, and additive rather than modifying Utopia's core entity tables.
