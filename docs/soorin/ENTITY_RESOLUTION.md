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

## Persistent registry status: implemented, deliberately dormant

Migrations `0111` and `0112` add Soorin-owned canonical identities, source-authority mappings, append-only observations, temporal alias history, and audited conflicts. Registry writes are transactional and concurrency-safe; composite foreign keys prevent cross-KB authority, alias, and conflict edges. Conflicting candidate identities are marked `ambiguous`, and linking a canonical identity to a Utopia entity is a same-KB compare-and-set.

This is **Option B for the Foundation release**: no active normalizer, Statements, or ingestion caller invokes the registry yet. Deterministic canonical keys remain the live Python/Statements identity behavior. Database tables existing is not evidence that registry-backed resolution is active.

Sprint 2 activation must be one explicit ingestion transaction boundary:

1. Resolve the authenticated tenant to one target Utopia KB.
2. Register every authoritative source tuple and append its evidence observation.
3. Stop on `Conflict`; never push the ambiguous candidate as a usable entity.
4. Record aliases with source evidence and validity interval.
5. Render Statements with the resolved canonical key.
6. After Utopia materializes the concrete entity, link it with `link_utopia_entity` compare-and-set.
7. Emit metrics/audit IDs and test concurrent replay, rollback, and cross-tenant isolation against PostgreSQL.

Do not partially wire only the normalizer or only the Statements client; that would create two identity authorities without an atomic reconciliation boundary.
