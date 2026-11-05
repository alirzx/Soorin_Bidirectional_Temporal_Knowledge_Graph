# Security boundaries and storage policy

## Admission and tenant ownership

A native ingestion source must be kind `statements` and have a valid source
bearer token. A KB administrator binds tenant/source-system/source-instance;
client tenant text is checked against that binding, never trusted as ownership.
Context requires existing reader access and matching KB tenant. Receipt listing
and retry require KB administration and return operational fields only.

Privacy tenants are a separate boundary: `UTOPIA_PRIVACY_TENANT_MAP` maps trusted
workspace UUIDs to canonical tenant UUIDs. Synthetic labels such as `tenant-blue`
are not gateway UUIDs. Workspace users cannot alter deployment origin allowlists.
Release binaries ignore the environment test-mode shortcut; debug test binaries
permit loopback mocks only. No test-mode override is set in production.

## Storage profile

| Data | Default policy |
|---|---|
| Durable canonical/source IDs and tenant/network scope | Retain for resolution and provenance; access-controlled personal/security data |
| Curated source metadata and attributed assertions | Retain bounded canonical structured fields; assertion is not verified observation |
| Evidence references, source IDs, URI, checksum and field path | Retain; source payload stays at source authority |
| Evidence excerpt | Native ingestion rejects nonempty excerpt by default |
| Raw logs, credentials, free vendor payload | Normalizer omits raw vendor extensions; recursive known sensitive keys are stripped before checksum creation; native admission rejects such structured keys |

`UTOPIA_SOC_ALLOW_SENSITIVE_PAYLOAD=1` is an explicit deployment exception for
approved retention, never a client option. It permits bounded excerpts/extensions
and requires a documented owner, purpose, retention/access policy and source
authorization. Production Compose sets it to `0`. The generic canonical Python
contract remains able to read historical payloads; `validate_native_event` checks
the stricter admission profile without changing checksum algorithms.

This is structural minimization, **not** a content DLP guarantee: arbitrary strings
can contain sensitive information. Operators must curate source fields and avoid
credential-bearing URIs or free-text secrets. Fact literals and identifiers may
legitimately contain sensitive SOC data. Receipt payloads and graph values are
not encrypted field-by-field; use encrypted disks/backups and restricted database
access. No retention deletion job is introduced by this pass. Do not copy raw
production events into tests or reports.

## Model and transport boundaries

Native chat, embeddings, reranking, extraction and alignment follow deployment
origin policy. HTTP redirects are disabled. Protected external text calls use
context → encode → provider → decode → validate → cleanup. Unknown aliases,
wrong tenant/context/profile, expired policy or malformed response fail closed.
Credentials are never decoded. Cancellation cleanup is best effort; gateway TTL
bounds abandoned contexts after a process crash. Gateway/provider credentials
must be separate and delivered through secret management.

Binary OCR/transcription cannot use text tokenization; they require a separately
trusted internal origin. Client construction fails instead of falling back to an
unrestricted HTTP client. See [Outbound privacy](OUTBOUND_PRIVACY.md) for protocols.
Mock tests establish protocol handling, not live DLP effectiveness.

Model APIs in production are unauthenticated on an isolated internal Docker
network accessible only to app/model containers. The CPU service supports an
optional bearer token, but native reranker credentials are not yet wired. Do not
expose these APIs outside that trust boundary; shared networks require additional
authentication/proxy design and acceptance. TLS, egress firewall policy and secret
rotation remain operator responsibilities.

## Database and release control

Runtime role `utopia_app` is provisioned before owner migrations; existing roles
are not silently rotated. Passwords are passed as quoted psql variables, not SQL
interpolation. Migration 10003 revokes runtime access to SQLx's ledger and indexes
receipt listing. Maintain a separate backup identity. The app still holds the
migration DSN for vector-index DDL; this is a documented privilege-reduction limit.

Release CI requires successful latest CI at the exact SHA, including migrations
and frontend. Configure required reviewers on the `production-release` GitHub
environment and branch protection; YAML alone cannot create those controls.
No release/tag/main merge is authorized by this engineering handoff.
