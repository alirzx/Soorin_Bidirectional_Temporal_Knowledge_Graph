# Deterministic and persistent identity

Python normalization handles Unicode NFKC, IDNA hosts, canonical IPs, Windows
principals/UPNs and MITRE identifiers. Canonical keys include tenant and the
required source/directory/network scope. Display names, embeddings and private
IP values alone are never authoritative merge evidence.

Migrations 0111/0112 implement canonical identities, source authorities,
observations, aliases, conflicts and same-KB compare-and-set Utopia links.
The registry is called by native Rust ingestion. The legacy Statements route
continues to exist but does not activate this registry.

The native authority key is `authority-v1:` followed by deterministic JSON of
`[authority_name, authority_value, scope_or_null]`. Array positions are fixed,
values are validated strings, object ordering cannot change this tuple, and
omitted/null scope have the same representation. Registry uniqueness also binds
KB, tenant, entity type, source system and source instance. Existing registry
history is never rewritten to this format.

Lifecycle: authorize source and tenant → persist receipt/job → register authority
and observations → record aliases → submit stable Statements → find canonical
Utopia entity → compare-and-set link → verify document and recognized typed
relations → mark receipt bound. Registration steps can survive a later failure;
the durable receipt resumes them. This is a recoverable journal, not one database
transaction spanning the entire asynchronous document pipeline.

A conflicting authority quarantines the receipt before Statements submission.
Provisional entities with authority mappings are rejected; value-only observations
do not claim trusted source authority. Quarantined receipts cannot be retried by
the retry endpoint. Review/reconciliation is explicit; no automatic merge/split
or quarantine override is implemented.

Concurrent registration and cross-KB constraints have database tests. Runtime
crash/recovery, alias history across revisions, and source-to-typed-graph behavior
must be repeated for the final built artifact in the controlled acceptance phase.
