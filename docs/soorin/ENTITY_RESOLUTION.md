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

### Provisional v1 compatibility characterization

Established v1 provisional keys omit source system/instance when authority is
absent. Thus Tenant A / Splunk / host-01 and Tenant A / EDR / host-01 can share a
provisional key; Tenant B differs. This is a known compatibility limit, not a
registry authority merge: provisional rows have no authority registration and the
resolver's `automatic` flag is false. Trusted aliases can propose candidates but
cannot supply missing authority.

Native ingestion uses an immutable KB tenant/source-system/source-instance binding,
so different source namespaces cannot enter the same native KB. The prepared API
regression rejects attempted rebinding with 409. Existing authority tuples and
network scopes remain distinct. Legacy direct Statements ingestion does not enforce
this native admission boundary; mixed-source provisional data requires separate
KBs or explicit review. Do not claim global collision-free provisional identities
or silently change keys to fix this limitation. Any future versioned key migration
must reconcile existing documents, aliases, registry links and historical evidence.
