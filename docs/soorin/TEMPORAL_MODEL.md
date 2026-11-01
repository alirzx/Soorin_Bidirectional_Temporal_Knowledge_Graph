# SOC temporal model

## Two axes

| SOC field | Utopia meaning |
|---|---|
| `event_time`, `valid_from`, `valid_to` | World time: when the assertion applied |
| `recorded_at`, `invalidated_at` | Knowledge time: when Utopia knew/retired it |
| `observed_at`, `ingested_at`, `processed_at` | Pipeline provenance; not replacements for world time |

The Statements adapter maps event time to `doc_time` and statement `when`. Utopia creates `recorded_at` and invalidates prior document-derived facts on revision. The adapter does not invent ledger timestamps.

## Revision classification

- Exact replay: same source key and checksum; no revision.
- New occurrence: different authoritative source record.
- Correction: same source record, changed content, no lifecycle change.
- State change: status changed; prior current state closes.
- Supersession/retraction: only when explicitly declared.
- Late arrival: same source record with event time older than the latest revision; retain without pretending it is current.

Historical revisions remain represented through Utopia's record axis. Queries use `at` for world time and `as_of` for knowledge time. Historical full-text recall remains incomplete because Tantivy retains current chunks only; graph/vector history is not evidence that BM25 history is complete.

`soorin/evaluation/temporal_cases.py` provides gold offline cases. A live isolated-KB experiment must still verify the exact deployed build's document/fact timeline before production claims.
