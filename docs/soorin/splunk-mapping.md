# Synthetic Splunk ES -> Soorin TKG field mapping

**No production export is included.** The examples approximate fields observed in Agentic SOC's Splunk normalizer and earlier password-spray investigations. All IPs use RFC 5737 TEST-NET ranges; hosts use the reserved `example` domain.

| Record | Splunk / Agentic SOC fields | TKG interpretation |
|---|---|---|
| ES notable | `search_name`, `orig_sid`, `index=notable`, `severity` | Notable event linked to a detection rule |
| Fused alert | `rule_name`, `severity`, `src_ip`, `username`, `host` | Alert event linked to notable, host, IP, user |
| Windows event | `_time`, `index`, `sourcetype`, `EventCode` or `EventID`, `Computer`, `IpAddress`, `AccountName` | Evidence event linked to host/IP/user and notable |
| SOC case | Case ID, status, severity, linked alerts/notables | Case node linked to evidence |
| Jira ticket | Issue key, status, referenced case | External ticket node linked to case |

Normalization precedence in the lab: `host` then `hostname` then `Computer`; `src_ip` then `src` then `source_ip` then `ClientIP` then `IpAddress`; `user` then `username` then `user_name` then `AccountName` then `User`; `EventID` then `EventCode`.

Agentic SOC also uses nested OCSF envelopes. The Sprint 1 adapter at
`soorin/adapters/splunk/llm_payload_normalizer.py` unwraps the canonical
envelope and curated `llm_payload`; the older rc9 mock generator remains
unchanged as a regression fixture.

## Seeded investigation scenario

The password spray is a **synthetic reconstruction of a previously discussed detection pattern**, not a copy of real logs:

- `SPLUNK-NOTABLE-001`: Password Spray Detection, MITRE ATT&CK `T1110.003`.
- 27 attempted usernames, 27 failures, zero successes, 2026-10-29T10:01:06Z to 10:02:26Z.
- `SPLUNK-ALERT-001/002` and two sample 4625 events, **not all 27 raw log rows**.
- `SOC-CASE-001` and `SOC-101` stand in for triage and Jira handoff.
- `SPLUNK-NOTABLE-002` and `SPLUNK-ALERT-003` represent a separate benign authorized registry change.

The dataset is intentionally small enough to inspect one evidence trail in the Graph UI.

## Current contract limitations

Source endpoint: `POST /api/v1/sources/{source_id}/statements`. Body fields are **strictly** `external_id`, `doc_time`, `deleted`, `e`, `s`, `n`. Each `s` row is `[null, subject, phrase, object-or-null, value-or-null, qualifiers, when, ended]`. This is an **open statement** contract; it does not accept `predicate`, `class`, or direct typed-fact insertion. Max body is 64 KiB and max 200 statements per push.

The UI's typed graph depends on resolution and alignment. No assertion is made that all 9 synthetic documents result in one connected typed graph without ontology/model configuration.
