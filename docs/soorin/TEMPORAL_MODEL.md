# SOC temporal model

| Clock | Meaning / authority |
|---|---|
| `event_time`, `valid_from`, `valid_to` | Source world/valid time |
| `observed_at` | Source observation/revision clock; must advance for automatic same-record replacement |
| Event `recorded_at`, `processed_at`, `delivery_id` | Adapter/delivery provenance; excluded from checksum v3 |
| Fact/receipt server `recorded_at` / `created_at` | Actual knowledge recording/delivery time |
| `at` | Query the world/valid axis |
| `as_of` | Query the server knowledge/record axis |

Opaque `source_revision_id` values identify revisions; they are not sortable
versions. Delivery order is not authority order. Exact checksum replay returns
the same receipt and active/terminal job. For the same source identity, an incoming
source `observed_at` less than or equal to an already submitted/bound observation
is quarantined if content differs. Its receipt retains historical evidence, but
it is not automatically projected into graph history. Equal-clock corrections
need review or a source-issued later observation. Event-time changes alone never
establish revision precedence. This conservative rule can quarantine legitimate
corrections whose upstream source lacks a reliable revision clock.

Utopia creates graph recording timestamps; client timestamps cannot backdate its
knowledge ledger. Native retractions (`invalidated_at`) require a separate review
workflow and are rejected at admission. Existing generic graph correction and
retraction operations retain their authorization rules.

Migration 10002 adds evidence attachment `recorded_at`: new links get server time;
legacy links remain NULL and are excluded from historical context. Never backfill
these with invented timestamps. Historical citations also require the document
version to be eligible at the requested knowledge time.

Historical context requires an entity UUID, not today's aliases or type filter.
Current display names, labels, disambiguators, closure names/values, evidence
filenames, later invalidation timestamps and nonhistorical metadata are withheld.
Facts are selected by both axes and conflicts use record-axis predicates. The
query reports truncation and missing citations as partial. `model_versions`
identifies deterministic graph lookup with no model usage.

Current lexical retrieval uses Tantivy; historical lexical retrieval uses
PostgreSQL `simple` tokenization with OR terms. Phrase, stemming and Persian
segmentation behavior differ. Neither identical numeric scores nor full historic
vector coverage is promised. Repeated database correction/deletion/restoration
and historical citation experiments remain required release gates.

### Explicit source update clocks

The Splunk normalizer now prefers source `source_updated_at`, `updated_at` or
`last_modified` (raw envelope first, then curated payload) for `observed_at`.
Occurrence `event_time` remains unchanged. It does not use the adapter's delivery
`observed_at` argument or server processing time as a replacement source clock.
Without an explicit update clock, equal-clock changed revisions remain quarantined;
opaque revision IDs do not establish order. No new event field, key algorithm,
checksum version or migration was introduced. Newly normalized content may differ
because a real source revision clock is now represented correctly; rehearse producer
upgrades on a dedicated source before resuming an older producer.
