-- Keep every identity-registry edge inside one knowledge base and make alias
-- observations append-only.  0111 is already an applied SQLx migration and
-- therefore remains byte-stable; this migration tightens its constraints.

ALTER TABLE soorin_canonical_identities
    ADD CONSTRAINT soorin_canonical_identities_kb_id_id_key UNIQUE (kb_id, id),
    ADD CONSTRAINT soorin_canonical_identities_authority_scope_key
        UNIQUE (kb_id, id, tenant_id, entity_type);

ALTER TABLE soorin_identity_authorities
    DROP CONSTRAINT IF EXISTS soorin_identity_authorities_identity_id_fkey,
    ADD CONSTRAINT soorin_identity_authorities_scope_key
        UNIQUE (kb_id, id, tenant_id, entity_type),
    ADD CONSTRAINT soorin_identity_authorities_identity_scope_fkey
        FOREIGN KEY (kb_id, identity_id, tenant_id, entity_type)
        REFERENCES soorin_canonical_identities (kb_id, id, tenant_id, entity_type)
        ON DELETE CASCADE;

ALTER TABLE soorin_identity_aliases
    ADD COLUMN provenance_hash BYTEA,
    ADD COLUMN first_seen_at TIMESTAMPTZ,
    ADD COLUMN last_seen_at TIMESTAMPTZ,
    ADD COLUMN occurrence_count BIGINT NOT NULL DEFAULT 1 CHECK (occurrence_count > 0);

-- PostgreSQL text cannot contain NUL. Hash a canonical JSONB tuple,
-- normalizing valid-time timestamps to UTC so sessions use the same hash.
-- The Rust record_alias INSERT must use the identical expression.
UPDATE soorin_identity_aliases
SET provenance_hash = sha256(convert_to(
        jsonb_build_array(
            alias, normalized_alias,
            to_char(valid_from AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISSUS'),
            to_char(valid_to AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISSUS'),
            provenance
        )::text, 'UTF8'
    )),
    first_seen_at = recorded_at,
    last_seen_at = recorded_at;

-- 0111 declared an unnamed UNIQUE constraint. PostgreSQL truncates generated
-- identifiers to 63 bytes, so a guessed DROP CONSTRAINT name silently fails.
-- Locate the exact unique key by ordered columns before replacing it.
DO $
DECLARE legacy_unique name;
BEGIN
    SELECT con.conname INTO legacy_unique
    FROM pg_constraint AS con
    WHERE con.conrelid = 'soorin_identity_aliases'::regclass
      AND con.contype = 'u'
      AND (
          SELECT array_agg(att.attname ORDER BY col.ordinality)
          FROM unnest(con.conkey) WITH ORDINALITY AS col(attnum, ordinality)
          JOIN pg_attribute AS att
            ON att.attrelid = con.conrelid AND att.attnum = col.attnum
      ) = ARRAY['identity_id', 'normalized_alias', 'valid_from']::name[];

    IF legacy_unique IS NULL THEN
        RAISE EXCEPTION 'Legacy Soorin alias uniqueness constraint not found';
    END IF;
    EXECUTE format('ALTER TABLE soorin_identity_aliases DROP CONSTRAINT %I', legacy_unique);
END $;

ALTER TABLE soorin_identity_aliases
    ALTER COLUMN provenance_hash SET NOT NULL,
    ALTER COLUMN first_seen_at SET NOT NULL,
    ALTER COLUMN last_seen_at SET NOT NULL,
    DROP CONSTRAINT IF EXISTS soorin_identity_aliases_identity_id_fkey,
    ADD CONSTRAINT soorin_identity_aliases_identity_kb_fkey
        FOREIGN KEY (kb_id, identity_id)
        REFERENCES soorin_canonical_identities (kb_id, id)
        ON DELETE CASCADE,
    ADD CONSTRAINT soorin_identity_aliases_history_key
        UNIQUE NULLS NOT DISTINCT (identity_id, normalized_alias, valid_from, provenance_hash),
    ADD CONSTRAINT soorin_identity_aliases_seen_range_check
        CHECK (last_seen_at >= first_seen_at);

ALTER TABLE soorin_identity_conflicts
    ADD COLUMN tenant_id TEXT,
    ADD COLUMN entity_type TEXT;

UPDATE soorin_identity_conflicts c
SET tenant_id = a.tenant_id,
    entity_type = a.entity_type
FROM soorin_identity_authorities a
WHERE a.kb_id = c.kb_id AND a.id = c.authority_id;

ALTER TABLE soorin_identity_conflicts
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN entity_type SET NOT NULL,
    DROP CONSTRAINT IF EXISTS soorin_identity_conflicts_authority_id_fkey,
    DROP CONSTRAINT IF EXISTS soorin_identity_conflicts_existing_identity_id_fkey,
    DROP CONSTRAINT IF EXISTS soorin_identity_conflicts_candidate_identity_id_fkey,
    ADD CONSTRAINT soorin_identity_conflicts_authority_scope_fkey
        FOREIGN KEY (kb_id, authority_id, tenant_id, entity_type)
        REFERENCES soorin_identity_authorities (kb_id, id, tenant_id, entity_type)
        ON DELETE CASCADE,
    ADD CONSTRAINT soorin_identity_conflicts_existing_identity_scope_fkey
        FOREIGN KEY (kb_id, existing_identity_id, tenant_id, entity_type)
        REFERENCES soorin_canonical_identities (kb_id, id, tenant_id, entity_type)
        ON DELETE CASCADE,
    ADD CONSTRAINT soorin_identity_conflicts_candidate_identity_scope_fkey
        FOREIGN KEY (kb_id, candidate_identity_id, tenant_id, entity_type)
        REFERENCES soorin_canonical_identities (kb_id, id, tenant_id, entity_type)
        ON DELETE CASCADE;
