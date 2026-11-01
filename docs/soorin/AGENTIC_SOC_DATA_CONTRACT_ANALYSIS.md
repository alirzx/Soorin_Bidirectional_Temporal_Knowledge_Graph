# Agentic SOC data-contract analysis

## Revisions inspected

- `main` at `19a0ceeb5375f2dfb8d50760c883053e50b529e9`.
- `feature/remote-privacy-gateway-integration` at `11cd70c9dcd27a3bf91a364046e3ab86c0cdc201`.

The privacy branch changes LLM egress boundaries and related callers; it does not establish a TKG ingestion contract. This sprint made no changes to Agentic SOC.

## Implemented source flow

```text
Splunk connector enriched notable
  -> canonical connector envelope / OCSF
  -> fusion promoter lifts curated llm_payload
  -> RawAlert / FusedAlert
  -> tenant-scoped Postgres alert row
  -> Auto-Triage compact evidence context
```

Primary source files:

- `services/connectors/app/connectors/splunk.py`: constructs the notable identity, source fields, rule metadata, macro definitions, time source, `llm_payload`, and `analyst_labels`.
- `services/fusion/app/services/promoter.py`: promotes canonical OCSF/envelope data and lifts `llm_payload` out of raw data.
- `services/fusion/app/models/alert.py`: `RawAlert`, `FusedAlert`, status/decision enums, tenant-scoped deterministic UUIDv5, and fingerprint semantics.
- `services/fusion/app/services/alert_sink.py`: tenant-scoped persistence, content deduplication, provenance fields, OCSF class, and `llm_payload` JSONB.
- `services/agents/app/workers/fused_alert_consumer.py`: builds agent state with first-class curated payload and provenance.
- `services/agents/app/context/auto_triage.py` and `tests/test_auto_triage_llm_payload.py`: curated payload is primary deterministic evidence; missing/malformed payload uses a bounded compact fallback and injection-like text is neutralized.
- `services/agents/app/integrations/splunk/normalizer.py`: converts investigation search rows into evidence records. It is distinct from the connector notable normalizer.

## Identity distinctions

| Identifier | Meaning | TKG treatment |
|---|---|---|
| Splunk Notable ID | Fired ES notable (`notable_id`, often `source_guid`/`source_event_id`) | `SplunkNotable` authoritative source identity |
| SOC Alert ID | Agentic SOC tenant alert UUID | `SecurityAlert` authoritative SOC identity; never substituted for notable ID |
| Source Event ID | Vendor event/finding identity | `SecurityEvent`/evidence reference and dedup input |
| Detection Rule ID | Saved search/detection configuration identity | `DetectionRule`; rule name is an alias, not authority |
| Incident ID | Fusion correlation incident | `Incident` |
| Case ID | Analyst case/workspace identity | `SOCCase` |
| TKG entity ID | Soorin canonical key | Derived tenant/source-scoped identity, never written back as a source ID |

Agentic SOC's `RawAlert.fingerprint()` prefers sorted vendor source-event IDs plus tenant and source. Without vendor IDs it falls back to rule/title/entities. `deterministic_id()` derives a UUIDv5 from tenant plus that fingerprint. The TKG preserves those decisions as source provenance but uses its own stable canonical key namespace.

## Current alert and lifecycle shape

`RawAlert` includes tenant, source, title/description, severity/status, IOC/entity fields, MITRE fields, raw event, curated payload, tags/risk, connector provenance, source-event IDs, OCSF class, rule ID/name, created time, and event time. `FusedAlert` adds fusion decision and incident/correlation results.

Alert statuses include `new`, `acknowledged`, `in_progress`, `resolved`, `suppressed`, and `fused`. Fusion decisions include `new_alert`, `duplicate`, `correlated`, and `new_incident`. Case and investigation APIs consistently include tenant predicates; reports and investigation runs are separate versionable artifacts.

## Semantic constraints preserved

- Splunk `risk_score` is accumulated vendor risk, not a probability. Some unrelated Agentic modules use normalized risk values; the field's producer/context must be retained.
- `event_time_source` explains whether event time came from a first event or alert-time fallback.
- Rule SPL/macro definitions are current configuration and are not proof of the fire-time configuration.
- An active allowlist is configuration context, not independent proof that activity was authorized.
- `investigation_hint` is retrieval guidance, not evidence.
- Analyst labels/assertions, reported source observations, deterministic inferences, and model conclusions are separate categories.
- Connector/source text is untrusted data and never instructions.

## Privacy branch relevance

The privacy feature centralizes remote LLM handling, canonical tenant context, TLS/fail-closed behavior, and egress inventory. Sprint 1 model adapters are compatible with a future protected base URL but do not call or modify that gateway. Production-sensitive documents must not be sent to an external endpoint until an approved privacy route and policy exist.
