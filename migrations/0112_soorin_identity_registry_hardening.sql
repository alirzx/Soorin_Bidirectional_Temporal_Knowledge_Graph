-- Keep every identity-registry edge inside one knowledge base and make alias
-- observations append-only.  0111 is already an applied SQLx migration and
-- therefore remains byte-stable; this migration tightens its constraints.

ALTER TABLE soorin_canonical_identities
    ADD CONSTRAINT soorin_canonical_identities_kb_id_id_key UNIQUE (kb_id, id),
    ADD CONSTRAINT soorin_canonical_identities_authority_scope_key
        UNIQUE (kb_id, id, tenant_id, entity_type);

ALTER TABLE soorin_identity_authorities
    DROP CONSTRAINT IF EXISTS soorin_identity_authorities_identity_id_fkey,
    ADD CONSTRAINT soorin_identity_authorities_identity_scope_fkey
        FOREIGN KEY (kb_id, identity_id, tenant_id, entity_type)
        REFERENCES soorin_canonical_identities (kb_id, id, tenant_id, entity_type)
        ON DELETE CASCADE;

ALTER TABLE soorin_identity_aliases
    ADD COLUMN provenance_hash BYTEA,
    ADD COLUMN first_seen_at TIMESTAMPTZ,
    ADD COLUMN last_seen_at TIMESTAMPTZ,
    ADD COLUMN occurrence_count BIGINT NOT NULL DEFAULT 1 CHECK (occurrence_count > 0);

UPDATE soorin_identity_aliases
SET provenance_hash = sha256(convert_to(
        alias || chr(0) || normalized_alias || chr(0)
        || COALESCE(valid_from::text, '') || chr(0)
        || COALESCE(valid_to::text, '') || chr(0)
        || provenance::text,
        'UTF8'
    )),
    first_seen_at = recorded_at,
    last_seen_at = recorded_at;

ALTER TABLE soorin_identity_aliases
    ALTER COLUMN provenance_hash SET NOT NULL,
    ALTER COLUMN first_seen_at SET NOT NULL,
    ALTER COLUMN last_seen_at SET NOT NULL,
    DROP CONSTRAINT IF EXISTS soorin_identity_aliases_identity_id_fkey,
    DROP CONSTRAINT IF EXISTS soorin_identity_aliases_identity_id_normalized_alias_valid_from_key,
    ADD CONSTRAINT soorin_identity_aliases_identity_kb_fkey
        FOREIGN KEY (kb_id, identity_id)
        REFERENCES soorin_canonical_identities (kb_id, id)
        ON DELETE CASCADE,
    ADD CONSTRAINT soorin_identity_aliases_history_key
        UNIQUE NULLS NOT DISTINCT (identity_id, normalized_alias, valid_from, provenance_hash),
    ADD CONSTRAINT soorin_identity_aliases_seen_range_check
        CHECK (last_seen_at >= first_seen_at);

ALTER TABLE soorin_identity_conflicts
    DROP CONSTRAINT IF EXISTS soorin_identity_conflicts_authority_id_fkey,
    DROP CONSTRAINT IF EXISTS soorin_identity_conflicts_existing_identity_id_fkey,
    DROP CONSTRAINT IF EXISTS soorin_identity_conflicts_candidate_identity_id_fkey,
    ADD CONSTRAINT soorin_identity_conflicts_authority_kb_fkey
        FOREIGN KEY (kb_id, authority_id)
        REFERENCES soorin_identity_authorities (kb_id, id)
        ON DELETE CASCADE,
    ADD CONSTRAINT soorin_identity_conflicts_existing_identity_kb_fkey
        FOREIGN KEY (kb_id, existing_identity_id)
        REFERENCES soorin_canonical_identities (kb_id, id)
        ON DELETE CASCADE,
    ADD CONSTRAINT soorin_identity_conflicts_candidate_identity_kb_fkey
        FOREIGN KEY (kb_id, candidate_identity_id)
        REFERENCES soorin_canonical_identities (kb_id, id)
        ON DELETE CASCADE;
