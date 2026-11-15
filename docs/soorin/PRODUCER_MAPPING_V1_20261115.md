# Producer → TKG mapping v1 — source review, 2026-11-15

Reference: Agentic_SOC `a0a160d1dfbd83304fbb335b8ef8ba871a04cd90`.
Its checkout was read only. This is a source-contract audit, not live integration.
All following producers still require the immutable TKG KB scope
`tenant_id + source_system=splunk + source_instance`. Independent producers cannot
share an asserted identity by merely reusing display names.

| Producer / envelope | Field path and type | Authority / canonical type | Time / evidence | Missing / validation | Coverage / remaining gate |
|---|---|---|---|---|---|
| Connector rich SPL and `_build_llm_payload` | `llm_payload.alert_id`: string | Legacy Splunk Notable, not SOC row UUID | `event_time` occurrence; `alert_time` explicit fallback | No UUID-shape inference | Existing normalizer fixtures; real rich/simple producer replay pending |
| API `build_llm_payload` | `_meta.mode=enriched_from_api`, `llm_payload.alert_id`: string | Durable `alerts.id` → SecurityAlert | Producer event time; enrichment time is not revision ordering | Conflicting envelope ID rejected | Python regression covers marker; live persistence pending |
| Fusion sink / fused consumer | `alert_row_id`, nested `alert.id`: UUID/string | Durable SOC alert row → SecurityAlert | Fusion/run processing time distinct from source clock | Bare arbitrary `id` without supported envelope is not guessed | Native canonical fixture + mapping review |
| Splunk / API row | `notable_id`, `source_guid`: string | `splunk_notable_id` → SplunkNotable | Source checksum and source references | Names/search titles never replace missing notable authority | Replay and separate-alert/same-notable identity fixtures |
| Fusion / OCSF | `source_event_ids`: string array; `finding.uid`: string | SecurityEvent references; Finding UID remains identified separately in verified metadata | No claim that Finding UID is original raw SIEM event ID | Never convert Finding UID into authoritative SOC Alert/Notable | OCSF JSON-string tests; runtime evidence checks pending |
| API / connector | `rule_id`, `detection_id`, `finding.rule_uid`: string | DetectionRule authority; rule title only display/provisional | Current rule config may differ from fire-time config | Missing ID stays provisional | Reviewed detected_by signature; real graph acceptance pending |
| Structured records | `risk_object`/`risk_object_type`, `entity`/`entity_type` | Exact local host/system/device, user/account, IP hints | Field path retained; unknown/missing hint warns and stays unresolved | No default definitive type for unknown hints | Mixed/nested arrays and unknown hints unit tested |
| API affected collections | `affected_hosts`, `affected_assets`, `affected_users`, `affected_ips`: arrays | Host/UserAccount/IPAddress observations, generally provisional | Source field and explicit network scope preserved | Invalid values rejected; aliases do not create authority | Scalar lists, nested mappings, network scope fixtures |
| Fusion `_entities` / `_iocs` | `entities[].{type,value}`, `iocs[].{type,value}` | Exact reviewed host/user/IP and IP/hash/domain/URL vocabularies | Field path including list index preserved | Unknown type not inferred; hash/URL validated | Dedicated unit regression; no arbitrary typed JSON support |
| OCSF wrapper / API `_unwrap_splunk_stash` | `raw_data`: encoded JSON object, nested `raw_event` | Unwrap source observations only | Preserve source evidence checksum | Duplicate keys, malformed JSON, depth and scope mismatch rejected | Stdlib-only subprocess + normalizer tests |
| Connector → fusion → API | `llm_payload`: object/encoded object/NULL | Explicit marker selects authority; payload absence permits compact fallback | Source checksum v3, no raw payload storage by default | Nested supported payload recovered; malformed HTTP payload rejected | Native/checksum/profile regressions |
| Agent fused consumer | `investigation_run_id`, `case_id`, `report_id`, `evidence_id` when supplied | Distinct InvestigationRun / SOCCase / Report / evidence references | Do not infer IDs from model text or confidence | Missing explicit authority is not invented | Existing relation/identity fixtures; no live Agentic_SOC investigation executed |

Inspected paths include connector `splunk.py`, fusion `models/alert.py` and
`services/alert_sink.py`, API `models/alert.py`, `splunk_enrichment.py`,
`splunk_notable.py`, and agent `workers/fused_alert_consumer.py`. The sink writes
`llm_payload`, `raw_event`, connector provenance and source-event IDs separately.
The consumer carries the durable row ID and derives its run ID separately.

Confidence, vendor risk score, model narrative and retrieval hints remain
non-authoritative. OCSF Finding is a supported source reference, not a newly
introduced ontology class. Canonical event v1 and checksum v3 are unchanged.
