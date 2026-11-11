# Agentic SOC data-contract analysis

## Revisions inspected

- `main` at `19a0ceeb5375f2dfb8d50760c883053e50b529e9`.
- `feature/remote-privacy-gateway-integration` at `11cd70c9dcd27a3bf91a364046e3ab86c0cdc201`.

The privacy branch changes LLM egress boundaries and related callers; it does not establish a TKG ingestion contract. This sprint made no changes to Agentic SOC.

The final pre-build audit re-read both local refs on 2026-11-02. The active Agentic checkout was clean on the privacy feature at the hash above; no fetch, checkout, edit, test mutation, or write was performed there.

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

The current connector query computes `notable_id` from `source_guid`, `source_event_id`, `event_id`, then `orig_sid@@orig_rid`; its curated `llm_payload.alert_id` is that notable ID. Fusion separately places OCSF `finding.uid` in `source_event_ids` and refuses to reuse it as `rule_id`. The fused worker chooses the durable SOC row as `message.alert_row_id`, then `message.id`, then `alert.id`. These are distinct authorities and the Soorin normalizer preserves each in its own entity/evidence field.

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

The Auto-Triage path continues to treat the curated payload as untrusted data, not instructions. Risk scores, current rule/macro configuration, and `investigation_hint` retain their caveats. A future TKG connector must consume a durable, versioned Agentic envelope at an authenticated boundary; it must not scrape prompt context or infer authority from the privacy branch.

## Final engineering recheck — 2026-11-05

The same main/privacy references were inspected read-only. Fusion persistence
outcomes, durable `alert_row_id`, curated `llm_payload` propagation and privacy
REST create/encode/decode/delete fields were rechecked against source. The local
Agentic_SOC checkout remained clean. Soorin's native transport and read-only
consumer contract are now in [Integration v1](AGENTIC_SOC_INTEGRATION_V1.md).
The normalizer now omits raw vendor extensions and sensitive structured keys;
source evidence checksums/references preserve provenance. Earlier broad retention
examples in this historical audit are not the current default storage policy.

## V1 baseline update

Current source reference is main `a0a160d1dfbd83304fbb335b8ef8ba871a04cd90`; the older branch analysis above is historical. The API enrichment builder now emits alerts.id in payload alert_id when `_meta.mode=enriched_from_api`. TKG explicitly distinguishes that contract from legacy curated notables. See [updated workflow audit](AGENT_TOOL_CONTRACTS.md).
