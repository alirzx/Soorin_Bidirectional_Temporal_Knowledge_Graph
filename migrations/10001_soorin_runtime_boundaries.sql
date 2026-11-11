-- Soorin extensions use 10000+; never renumber applied upstream/Soorin history.
CREATE TABLE soorin_workspace_runtime (
    workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    reranker JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE chunks ADD COLUMN embedding_model TEXT;
CREATE TABLE soorin_kb_tenants (
    kb_id UUID PRIMARY KEY REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL CHECK (length(btrim(tenant_id)) > 0),
    source_system TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE soorin_ingestion_receipts (
    id UUID PRIMARY KEY,
    kb_id UUID NOT NULL REFERENCES soorin_kb_tenants(kb_id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    checksum TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','registered','submitted','bound','quarantined')),
    failure_code TEXT,
    job_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_id, source_key, checksum)
);
CREATE TABLE soorin_ingestion_leases (
    source_id UUID PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    owner UUID NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
