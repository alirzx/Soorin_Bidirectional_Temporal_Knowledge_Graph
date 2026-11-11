-- Payload-free receipt diagnostics use KB + descending creation order.
CREATE INDEX soorin_receipts_kb_created ON soorin_ingestion_receipts(kb_id, created_at DESC);
-- An application credential must not edit SQLx's migration ledger.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utopia_app') THEN
        REVOKE ALL ON _sqlx_migrations FROM utopia_app;
    END IF;
END
$$;
