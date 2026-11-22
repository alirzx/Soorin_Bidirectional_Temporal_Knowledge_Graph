-- Existing unversioned outcomes remain unknown for purposes of a permanent rejection.
ALTER TABLE jobs ADD COLUMN document_version integer;
CREATE INDEX jobs_running_soc_source ON jobs ((payload->>'source_id'))
    WHERE kind='soc_ingest' AND status='running';

CREATE VIEW soorin_failed_document_dependencies AS
SELECT d.id AS document_id,d.kb_id,d.source_id,d.external_key,stage.kind,
       CASE WHEN latest.status='failed' AND latest.document_version=(
           SELECT max(v.version) FROM document_versions v WHERE v.document_id=d.id)
            THEN latest.failure_class END AS failure_class,
       EXISTS(SELECT 1 FROM jobs j WHERE j.kind=stage.kind
              AND j.payload->>'document_id'=d.id::text AND j.status IN ('queued','running')) AS active
FROM documents d
CROSS JOIN LATERAL (SELECT CASE WHEN d.status='failed' THEN 'process_document'
                                ELSE 'extract_document' END AS kind) stage
LEFT JOIN LATERAL (
    SELECT j.status,j.document_version,j.failure_class FROM jobs j
    WHERE j.kind=stage.kind AND j.payload->>'document_id'=d.id::text ORDER BY j.id DESC LIMIT 1
) latest ON true
WHERE d.deleted_at IS NULL AND (d.status='failed' OR d.graph_status='failed');

CREATE OR REPLACE VIEW soorin_receipt_delivery AS
SELECT r.id,r.kb_id,j.status AS job_status,j.failure_class,
       CASE WHEN r.status IN ('bound','quarantined') THEN r.status
            WHEN f.document_id IS NOT NULL AND NOT f.active THEN
                CASE WHEN f.failure_class='terminal' THEN 'terminal_failure' ELSE 'failed_recoverable' END
            WHEN j.status='failed' AND j.failure_class='terminal' THEN 'terminal_failure'
            WHEN j.status='failed' THEN 'failed_recoverable'
            WHEN j.status='running' THEN 'running'
            WHEN f.active OR (j.status='queued' AND j.failure_class='deferred') THEN 'waiting_for_dependency'
            WHEN j.status='queued' THEN 'queued'
            WHEN r.status IN ('registered','submitted') OR j.status='done' THEN 'failed_recoverable'
            ELSE 'accepted' END AS delivery_state
FROM soorin_ingestion_receipts r LEFT JOIN jobs j ON j.id=r.job_id
LEFT JOIN soorin_failed_document_dependencies f ON r.status='submitted' AND f.source_id=r.source_id
 AND f.kb_id=r.kb_id AND f.external_key='statements:soorin-soc-v2:' || (r.payload->>'tenant_id') || ':' ||
 left(encode(sha256(convert_to(r.source_key,'UTF8')),'hex'),24);
