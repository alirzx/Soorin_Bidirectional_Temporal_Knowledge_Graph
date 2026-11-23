-- Optional ownership for guarded synthetic admissions. Existing producers omit it.
ALTER TABLE soorin_ingestion_receipts ADD COLUMN acceptance_run uuid;
CREATE INDEX soorin_receipts_run_page ON soorin_ingestion_receipts
    (kb_id, acceptance_run, created_at DESC, id DESC) WHERE acceptance_run IS NOT NULL;
CREATE INDEX jobs_running_soc_enrichment ON jobs (id)
    WHERE kind='soc_reembed_document' AND status='running';
