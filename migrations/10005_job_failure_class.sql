-- NULL also covers legacy jobs whose failure category cannot be reconstructed.
ALTER TABLE jobs ADD COLUMN failure_class text
    CHECK (failure_class IN ('terminal','deferred','unknown'));
CREATE INDEX jobs_document_dependency ON jobs ((payload->>'document_id'),kind,id DESC)
    WHERE kind IN ('process_document','extract_document','soc_reembed_document');

-- One public lifecycle projection for both the list and individual receipt.
CREATE VIEW soorin_receipt_delivery AS
SELECT r.id, r.kb_id, j.status AS job_status, j.failure_class,
       CASE WHEN r.status IN ('bound','quarantined') THEN r.status
            WHEN j.status='failed' AND j.failure_class='terminal' THEN 'terminal_failure'
            WHEN j.status='failed' OR r.failure_code='soc_document_repair_required' THEN 'failed_recoverable'
            WHEN j.status='running' THEN 'running'
            WHEN j.status='queued' AND j.failure_class='deferred' THEN 'waiting_for_dependency'
            WHEN j.status='queued' THEN 'queued'
            ELSE 'accepted' END AS delivery_state
FROM soorin_ingestion_receipts r LEFT JOIN jobs j ON j.id=r.job_id;
