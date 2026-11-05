# Splunk `llm_payload` field mapping

> Historical checkpoint. Current behavior and evidence are in [Final acceptance](FINAL_ACCEPTANCE_REPORT.md) and [Production architecture](PRODUCTION_ARCHITECTURE.md).

| Current Agentic field | Source meaning | Soorin category | Notes |
|---|---|---|---|
| `alert_id` | Connector notable identity in the curated payload | Verified source identity only when corroborated by source envelope | Kept distinct from SOC alert UUID |
| `alert_time` | Notable/alert timestamp | Verified source metadata | Fallback world time when event time is unavailable |
| `event_time` | Best event timestamp | World/valid time | Normalized to UTC |
| `event_time_source` | Timestamp origin/confidence | Verified source metadata | `first_event`, `alert_time_fallback`, or unknown |
| `date_context` | Derived weekday/hour/business-hours context | Reported observation | Derived context, not event evidence |
| `rule_name` | Saved-search/detection display name | Detection rule alias | Rule ID is preferred authority |
| `severity` | Vendor/SOC severity label | Reported observation | Not a malicious probability |
| `finding_count` | Count of matched findings | Reported observation | Numeric type retained |
| `risk_score` | Accumulated Splunk risk | Reported observation | Explicitly not normalized probability |
| `risk_object`, `risk_object_type` | Risk entity | Entity mention | Type-aware extraction |
| `entity`, `entity_type` | Primary affected entity | Entity mention | Host/user/IP hint validated before use |
| `detection_type`, `security_domain`, `investigation_type` | Classification/context | Reported observation | Never canonical identity |
| `time_window` | Search/notable time bounds and source | Reported configuration context | Not substituted for event time |
| `annotations` | MITRE/story/CVE/etc. mappings | Reported mapping | MITRE IDs validated |
| `rule.title`, `description` | Rendered rule text | Rule configuration | Current configuration caveat retained |
| `rule.title_template`, `description_template` | Pre-expansion template | Rule configuration | Kept separate from rendered text |
| `rule.risk_message`, `next_steps` | Rule guidance | Rule configuration | Guidance, not event evidence |
| `rule.spl` | Current saved search | Rule configuration | Excluded from regex entity sweep and default embedding text |
| `rule.spl_caveat` | Producer caveat | Provenance/caveat | Retained |
| `rule.macro_definitions` | Current macros | Rule configuration | Excluded from regex entity sweep |
| `rule.macro_definitions_caveat` | Producer caveat | Provenance/caveat | Active filters do not prove authorization |
| `investigation_hint` | Contributing-events query guidance | Retrieval hint | Never a fact or instruction |
| `alert_fields` | Rule-specific structured fields | Reported observations + field-aware extraction | Unknown fields retained deliberately |

## Envelope and historical fields

The adapter also retains `analyst_labels`, `notable_raw` references, `source_guid`, `source_event_id`, `detection_id`, `orig_sid`, `orig_rid`, `event_id`, `rule_id`, and `search_name`. Identity precedence is source envelope first, curated payload second. Missing or malformed `llm_payload` produces an explicit warning and compact structured fallback; prompt-formatted text is never treated as the authoritative source.

Nested OCSF envelopes are unwrapped without flattening away the original `vendor_fields`. The synthetic fixture `soorin/tests/fixtures/soc_llm_payload_scenarios_v1.json` covers all supported variants and contains no private records.
