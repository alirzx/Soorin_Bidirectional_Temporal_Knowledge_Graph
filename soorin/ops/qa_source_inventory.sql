-- Read-only, payload-free snapshot. psql -v kb_id=UUID -f this-file
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10s';
SELECT jsonb_build_object(
  'kb_id', :'kb_id',
  'migrations', (SELECT count(*) FROM _sqlx_migrations WHERE success),
  'latest_migration', (SELECT max(version) FROM _sqlx_migrations WHERE success),
  'documents', (SELECT count(*) FROM documents WHERE kb_id=:'kb_id'::uuid),
  'live_documents', (SELECT count(*) FROM documents WHERE kb_id=:'kb_id'::uuid AND deleted_at IS NULL AND purged_at IS NULL),
  'document_versions', (SELECT count(*) FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE d.kb_id=:'kb_id'::uuid),
  'chunks', (SELECT count(*) FROM chunks WHERE kb_id=:'kb_id'::uuid),
  'live_chunks', (SELECT count(*) FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.kb_id=:'kb_id'::uuid AND c.superseded_at IS NULL AND d.deleted_at IS NULL AND d.purged_at IS NULL),
  'entities', (SELECT count(*) FROM entities WHERE kb_id=:'kb_id'::uuid),
  'live_entities', (SELECT count(*) FROM entities WHERE kb_id=:'kb_id'::uuid AND merged_into IS NULL),
  'facts_including_history', (SELECT count(*) FROM facts WHERE kb_id=:'kb_id'::uuid),
  'live_facts', (SELECT count(*) FROM facts WHERE kb_id=:'kb_id'::uuid AND invalidated_at IS NULL),
  'typed_facts', (SELECT count(*) FROM facts WHERE kb_id=:'kb_id'::uuid AND layer='typed'),
  'fact_evidence', (SELECT count(*) FROM fact_evidence e JOIN facts f ON f.id=e.fact_id WHERE f.kb_id=:'kb_id'::uuid),
  'typed_fact_sources', (SELECT count(*) FROM typed_fact_sources s JOIN facts f ON f.id=s.fact_id WHERE f.kb_id=:'kb_id'::uuid),
  'canonical_identities', (SELECT count(*) FROM soorin_canonical_identities WHERE kb_id=:'kb_id'::uuid),
  'authority_links', (SELECT count(*) FROM soorin_canonical_identities WHERE kb_id=:'kb_id'::uuid AND utopia_entity_id IS NOT NULL),
  'authority_mappings', (SELECT count(*) FROM soorin_identity_authorities WHERE kb_id=:'kb_id'::uuid),
  'receipts', (SELECT count(*) FROM soorin_ingestion_receipts WHERE kb_id=:'kb_id'::uuid),
  'bound_receipts', (SELECT count(*) FROM soorin_ingestion_receipts WHERE kb_id=:'kb_id'::uuid AND status='bound'),
  'duplicate_live_keys', (SELECT count(*) FROM (SELECT canonical_name FROM entities WHERE kb_id=:'kb_id'::uuid AND merged_into IS NULL AND canonical_name LIKE 'soorin:%' GROUP BY canonical_name HAVING count(*)>1) x)
);
SELECT e.canonical_name, count(*) AS candidate_count,
       array_agg(e.id ORDER BY e.id) AS candidate_ids
FROM entities e WHERE e.kb_id=:'kb_id'::uuid
  AND e.merged_into IS NULL AND e.canonical_name LIKE 'soorin:%'
GROUP BY e.canonical_name HAVING count(*)>1 ORDER BY e.canonical_name;
COMMIT;
