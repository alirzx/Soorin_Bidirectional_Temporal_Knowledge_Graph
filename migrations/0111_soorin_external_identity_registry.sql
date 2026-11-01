-- Soorin source authorities must survive process restarts and parallel workers.
-- Canonical identities are separate from authority mappings so several source
-- identifiers can deliberately resolve to one Utopia entity.
CREATE TABLE soorin_canonical_identities (
    id                UUID PRIMARY KEY,
    kb_id             UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    tenant_id         TEXT NOT NULL,
    entity_type       TEXT NOT NULL,
    canonical_key     TEXT NOT NULL,
    utopia_entity_id  UUID,
    status            TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'provisional', 'ambiguous', 'retired')),
    provenance        JSONB NOT NULL DEFAULT '{}',
    first_seen_at     TIMESTAMPTZ NOT NULL,
    last_seen_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (kb_id, canonical_key),
    FOREIGN KEY (kb_id, utopia_entity_id) REFERENCES entities(kb_id, id) ON DELETE SET NULL (utopia_entity_id),
    CHECK (length(btrim(tenant_id)) > 0 AND length(btrim(entity_type)) > 0 AND length(btrim(canonical_key)) > 0),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE TABLE soorin_identity_authorities (
    id                 UUID PRIMARY KEY,
    kb_id              UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    identity_id        UUID NOT NULL REFERENCES soorin_canonical_identities(id) ON DELETE CASCADE,
    tenant_id          TEXT NOT NULL,
    entity_type        TEXT NOT NULL,
    source_system      TEXT NOT NULL,
    source_instance    TEXT NOT NULL,
    source_identifier  TEXT NOT NULL,
    provenance         JSONB NOT NULL DEFAULT '{}',
    first_seen_at      TIMESTAMPTZ NOT NULL,
    last_seen_at       TIMESTAMPTZ NOT NULL,
    UNIQUE (kb_id, tenant_id, entity_type, source_system, source_instance, source_identifier),
    UNIQUE (kb_id, id),
    CHECK (length(btrim(source_system)) > 0 AND length(btrim(source_instance)) > 0
           AND length(btrim(source_identifier)) > 0),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE INDEX soorin_identity_authorities_identity_idx
    ON soorin_identity_authorities (kb_id, identity_id);

CREATE TABLE soorin_identity_observations (
    id                UUID PRIMARY KEY,
    kb_id             UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    authority_id      UUID NOT NULL,
    provenance_hash   BYTEA NOT NULL,
    provenance        JSONB NOT NULL,
    source_revision_id TEXT,
    first_seen_at     TIMESTAMPTZ NOT NULL,
    last_seen_at      TIMESTAMPTZ NOT NULL,
    occurrence_count  BIGINT NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    FOREIGN KEY (kb_id, authority_id) REFERENCES soorin_identity_authorities(kb_id, id) ON DELETE CASCADE,
    UNIQUE (authority_id, provenance_hash),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE TABLE soorin_identity_aliases (
    id                UUID PRIMARY KEY,
    kb_id             UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    identity_id       UUID NOT NULL REFERENCES soorin_canonical_identities(id) ON DELETE CASCADE,
    alias             TEXT NOT NULL,
    normalized_alias  TEXT NOT NULL,
    valid_from        TIMESTAMPTZ,
    valid_to          TIMESTAMPTZ,
    recorded_at       TIMESTAMPTZ NOT NULL,
    provenance        JSONB NOT NULL DEFAULT '{}',
    UNIQUE NULLS NOT DISTINCT (identity_id, normalized_alias, valid_from),
    CHECK (length(btrim(alias)) > 0 AND length(btrim(normalized_alias)) > 0),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE INDEX soorin_identity_aliases_lookup_idx
    ON soorin_identity_aliases (kb_id, normalized_alias);

CREATE TABLE soorin_identity_conflicts (
    id                    UUID PRIMARY KEY,
    kb_id                 UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    authority_id          UUID NOT NULL REFERENCES soorin_identity_authorities(id) ON DELETE CASCADE,
    existing_identity_id  UUID NOT NULL REFERENCES soorin_canonical_identities(id) ON DELETE CASCADE,
    candidate_identity_id UUID NOT NULL REFERENCES soorin_canonical_identities(id) ON DELETE CASCADE,
    reason                TEXT NOT NULL,
    provenance            JSONB NOT NULL DEFAULT '{}',
    first_seen_at         TIMESTAMPTZ NOT NULL,
    last_seen_at          TIMESTAMPTZ NOT NULL,
    occurrence_count      BIGINT NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    resolved_at           TIMESTAMPTZ,
    resolution            JSONB,
    CHECK (existing_identity_id <> candidate_identity_id),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE UNIQUE INDEX soorin_identity_conflicts_open_idx
    ON soorin_identity_conflicts (authority_id, candidate_identity_id)
    WHERE resolved_at IS NULL;
