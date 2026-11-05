# Isolated synthetic E2E validation

The current native harness is `python3 -m soorin.e2e.native_validation`. Without
`--execute` it reports NOT RUN. It requires `SOORIN_DISPOSABLE_ACCEPTANCE=1` for
live execution, accepts only loopback API port 2516 and creates fresh synthetic
accounts/KBs/sources. Existing deployments using that port must not be targeted.

It imports SOC ontology, binds the tenant, submits canonical events and replays,
polls receipts, checks typed relations, historical evidence, context/claims and
cross-tenant rejection. It writes incremental sanitized reports. Passing the
harness does not prove all crash/lease, migration, privacy or real-model cases;
see [Phase E](BUILD_AND_TEST_HANDOFF.md#phase-e--synthetic-soc-and-privacy).

`soorin.e2e.local_validation` remains a legacy Statements/offline fixture harness.
Its offline identity result is not evidence about the native persistent registry.
Do not present its lexical fallback as semantic inference or its open edges as
completed typed materialization. Never mix its Statements source with native
receipt ingestion. See [Integration contract](AGENTIC_SOC_INTEGRATION_V1.md).

No live E2E was executed in the final lightweight engineering pass. All real
inference, source-image startup and disposable-DB acceptance remain separate gates.
