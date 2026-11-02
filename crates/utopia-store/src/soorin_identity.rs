//! Persistent source-authority identity mappings for Soorin SOC ingestion.
//!
//! The external authority tuple is the concurrency boundary. Two workers may
//! propose the same mapping safely; a proposal to bind that tuple to a
//! different canonical identity is recorded as a conflict and never merged.

use chrono::{DateTime, Utc};
use serde_json::Value;
use sha2::{Digest, Sha256};
use sqlx::PgPool;
use utopia_core::{AppError, AppResult};
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct Registration<'a> {
    pub kb_id: Uuid,
    pub tenant_id: &'a str,
    pub entity_type: &'a str,
    pub source_system: &'a str,
    pub source_instance: &'a str,
    pub source_identifier: &'a str,
    pub canonical_key: &'a str,
    pub status: &'a str,
    pub source_revision_id: Option<&'a str>,
    pub observed_at: DateTime<Utc>,
    pub provenance: &'a Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegistrationOutcome {
    Resolved {
        identity_id: Uuid,
        authority_id: Uuid,
    },
    Conflict {
        conflict_id: Uuid,
        existing_identity_id: Uuid,
        candidate_identity_id: Uuid,
    },
}

fn required(value: &str, field: &str) -> AppResult<()> {
    if value.trim().is_empty() {
        return Err(AppError::Validation(format!("{field} cannot be empty")));
    }
    Ok(())
}

/// Register or re-observe an authoritative source identifier.
pub async fn register(pool: &PgPool, item: Registration<'_>) -> AppResult<RegistrationOutcome> {
    for (value, field) in [
        (item.tenant_id, "tenant_id"),
        (item.entity_type, "entity_type"),
        (item.source_system, "source_system"),
        (item.source_instance, "source_instance"),
        (item.source_identifier, "source_identifier"),
        (item.canonical_key, "canonical_key"),
    ] {
        required(value, field)?;
    }
    if !matches!(item.status, "active" | "provisional" | "ambiguous" | "retired") {
        return Err(AppError::Validation("invalid identity status".into()));
    }

    let mut tx = pool.begin().await?;
    let candidate_id = Uuid::now_v7();
    let candidate = sqlx::query_as::<_, (Uuid,)>(
        "INSERT INTO soorin_canonical_identities
             (id, kb_id, tenant_id, entity_type, canonical_key, status, provenance, first_seen_at, last_seen_at)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
         ON CONFLICT (kb_id, canonical_key) DO UPDATE
             SET last_seen_at = GREATEST(soorin_canonical_identities.last_seen_at, EXCLUDED.last_seen_at)
           WHERE soorin_canonical_identities.tenant_id = EXCLUDED.tenant_id
             AND soorin_canonical_identities.entity_type = EXCLUDED.entity_type
         RETURNING id",
    )
    .bind(candidate_id)
    .bind(item.kb_id)
    .bind(item.tenant_id)
    .bind(item.entity_type)
    .bind(item.canonical_key)
    .bind(item.status)
    .bind(item.provenance)
    .bind(item.observed_at)
    .fetch_optional(&mut *tx)
    .await?;
    let Some((candidate_identity_id,)) = candidate else {
        return Err(AppError::Conflict(
            "canonical key is already owned by another tenant or entity type".into(),
        ));
    };

    let proposed_authority_id = Uuid::now_v7();
    sqlx::query(
        "INSERT INTO soorin_identity_authorities
             (id, kb_id, identity_id, tenant_id, entity_type, source_system, source_instance,
              source_identifier, provenance, first_seen_at, last_seen_at)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)
         ON CONFLICT (kb_id, tenant_id, entity_type, source_system, source_instance, source_identifier)
         DO NOTHING",
    )
    .bind(proposed_authority_id)
    .bind(item.kb_id)
    .bind(candidate_identity_id)
    .bind(item.tenant_id)
    .bind(item.entity_type)
    .bind(item.source_system)
    .bind(item.source_instance)
    .bind(item.source_identifier)
    .bind(item.provenance)
    .bind(item.observed_at)
    .execute(&mut *tx)
    .await?;

    let (authority_id, existing_identity_id): (Uuid, Uuid) = sqlx::query_as(
        "SELECT id, identity_id FROM soorin_identity_authorities
          WHERE kb_id=$1 AND tenant_id=$2 AND entity_type=$3 AND source_system=$4
            AND source_instance=$5 AND source_identifier=$6",
    )
    .bind(item.kb_id)
    .bind(item.tenant_id)
    .bind(item.entity_type)
    .bind(item.source_system)
    .bind(item.source_instance)
    .bind(item.source_identifier)
    .fetch_one(&mut *tx)
    .await?;

    if existing_identity_id != candidate_identity_id {
        let proposed_conflict_id = Uuid::now_v7();
        let (conflict_id,): (Uuid,) = sqlx::query_as(
            "INSERT INTO soorin_identity_conflicts
                 (id, kb_id, authority_id, existing_identity_id, candidate_identity_id, reason,
                  provenance, first_seen_at, last_seen_at)
             VALUES ($1,$2,$3,$4,$5,'authority_tuple_already_bound',$6,$7,$7)
             ON CONFLICT (authority_id, candidate_identity_id) WHERE resolved_at IS NULL
             DO UPDATE SET last_seen_at=GREATEST(soorin_identity_conflicts.last_seen_at, EXCLUDED.last_seen_at),
                           occurrence_count=soorin_identity_conflicts.occurrence_count+1
             RETURNING id",
        )
        .bind(proposed_conflict_id)
        .bind(item.kb_id)
        .bind(authority_id)
        .bind(existing_identity_id)
        .bind(candidate_identity_id)
        .bind(item.provenance)
        .bind(item.observed_at)
        .fetch_one(&mut *tx)
        .await?;
        // A collision artifact may be retained for review and provenance, but
        // it must never look like an automatically usable canonical identity.
        sqlx::query(
            "UPDATE soorin_canonical_identities
                SET status='ambiguous'
              WHERE kb_id=$1 AND id=$2",
        )
        .bind(item.kb_id)
        .bind(candidate_identity_id)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;
        return Ok(RegistrationOutcome::Conflict {
            conflict_id,
            existing_identity_id,
            candidate_identity_id,
        });
    }

    sqlx::query(
        "UPDATE soorin_identity_authorities
            SET last_seen_at=GREATEST(last_seen_at,$2)
          WHERE id=$1",
    )
    .bind(authority_id)
    .bind(item.observed_at)
    .execute(&mut *tx)
    .await?;

    let mut hasher = Sha256::new();
    hasher.update(serde_json::to_vec(item.provenance).map_err(anyhow::Error::from)?);
    hasher.update([0]);
    hasher.update(item.source_revision_id.unwrap_or("").as_bytes());
    let provenance_hash = hasher.finalize().to_vec();
    sqlx::query(
        "INSERT INTO soorin_identity_observations
             (id,kb_id,authority_id,provenance_hash,provenance,source_revision_id,first_seen_at,last_seen_at)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$7)
         ON CONFLICT (authority_id, provenance_hash) DO UPDATE
             SET last_seen_at=GREATEST(soorin_identity_observations.last_seen_at, EXCLUDED.last_seen_at),
                 occurrence_count=soorin_identity_observations.occurrence_count+1",
    )
    .bind(Uuid::now_v7())
    .bind(item.kb_id)
    .bind(authority_id)
    .bind(provenance_hash)
    .bind(item.provenance)
    .bind(item.source_revision_id)
    .bind(item.observed_at)
    .execute(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(RegistrationOutcome::Resolved {
        identity_id: existing_identity_id,
        authority_id,
    })
}

/// Record a time-bounded alias without changing authority ownership.
pub async fn record_alias(
    pool: &PgPool,
    kb_id: Uuid,
    identity_id: Uuid,
    alias: &str,
    normalized_alias: &str,
    valid_from: Option<DateTime<Utc>>,
    valid_to: Option<DateTime<Utc>>,
    recorded_at: DateTime<Utc>,
    provenance: &Value,
) -> AppResult<Uuid> {
    required(alias, "alias")?;
    required(normalized_alias, "normalized_alias")?;
    if valid_from.zip(valid_to).is_some_and(|(start, end)| end < start) {
        return Err(AppError::Validation("alias valid_to precedes valid_from".into()));
    }
    let (id,): (Uuid,) = sqlx::query_as(
        "INSERT INTO soorin_identity_aliases
             (id,kb_id,identity_id,alias,normalized_alias,valid_from,valid_to,recorded_at,provenance,
              provenance_hash,first_seen_at,last_seen_at)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,
                 sha256(convert_to(
                     $4 || chr(0) || $5 || chr(0)
                     || COALESCE($6::timestamptz::text, '') || chr(0)
                     || COALESCE($7::timestamptz::text, '') || chr(0)
                     || $9::jsonb::text,
                     'UTF8'
                 )),$8,$8)
         ON CONFLICT (identity_id, normalized_alias, valid_from, provenance_hash)
         DO UPDATE SET last_seen_at=GREATEST(soorin_identity_aliases.last_seen_at, EXCLUDED.last_seen_at),
                       occurrence_count=soorin_identity_aliases.occurrence_count+1
         RETURNING id",
    )
    .bind(Uuid::now_v7())
    .bind(kb_id)
    .bind(identity_id)
    .bind(alias)
    .bind(normalized_alias)
    .bind(valid_from)
    .bind(valid_to)
    .bind(recorded_at)
    .bind(provenance)
    .fetch_one(pool)
    .await?;
    Ok(id)
}

/// Link a canonical source identity to the concrete entity in the same KB.
pub async fn link_utopia_entity(
    pool: &PgPool,
    kb_id: Uuid,
    identity_id: Uuid,
    entity_id: Uuid,
) -> AppResult<()> {
    // Atomic compare-and-set: first writer wins. Concurrent attempts to
    // link a different entity cannot overwrite the established binding.
    let result = sqlx::query(
        "UPDATE soorin_canonical_identities
            SET utopia_entity_id=$3
          WHERE kb_id=$1 AND id=$2
            AND (utopia_entity_id IS NULL OR utopia_entity_id=$3)
            AND EXISTS (SELECT 1 FROM entities WHERE kb_id=$1 AND id=$3)",
    )
    .bind(kb_id)
    .bind(identity_id)
    .bind(entity_id)
    .execute(pool)
    .await?;
    if result.rows_affected() == 0 {
        let found: Option<(Option<Uuid>,)> = sqlx::query_as(
            "SELECT utopia_entity_id FROM soorin_canonical_identities WHERE kb_id=$1 AND id=$2",
        )
        .bind(kb_id)
        .bind(identity_id)
        .fetch_optional(pool)
        .await?;
        match found {
            None => return Err(AppError::NotFound),
            Some((Some(other),)) if other != entity_id => {
                return Err(AppError::Conflict("identity is already linked to another Utopia entity".into()));
            }
            _ => return Err(AppError::Validation("Utopia entity does not belong to this knowledge base".into())),
        }
    }
    Ok(())
}
