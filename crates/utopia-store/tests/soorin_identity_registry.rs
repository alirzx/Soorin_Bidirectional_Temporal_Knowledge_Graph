use chrono::Utc;
use sqlx::PgPool;
use utopia_store::soorin_identity::{self, Registration, RegistrationOutcome};
use uuid::Uuid;

async fn seed(pool: &PgPool) -> anyhow::Result<(Uuid, Uuid)> {
    let (org, workspace, kb) = (Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7());
    let name = format!("soorin-identity-{kb}");
    sqlx::query("INSERT INTO organizations (id,name) VALUES ($1,$2)")
        .bind(org)
        .bind(&name)
        .execute(pool)
        .await?;
    sqlx::query("INSERT INTO workspaces (id,org_id,name) VALUES ($1,$2,$3)")
        .bind(workspace)
        .bind(org)
        .bind(&name)
        .execute(pool)
        .await?;
    sqlx::query("INSERT INTO knowledge_bases (id,workspace_id,name) VALUES ($1,$2,$3)")
        .bind(kb)
        .bind(workspace)
        .bind(&name)
        .execute(pool)
        .await?;
    Ok((org, kb))
}

#[tokio::test]
async fn concurrent_authority_registration_is_idempotent_and_conflicts_are_audited(
) -> anyhow::Result<()> {
    let Some(url) = utopia_store::test_db::url() else {
        return Ok(());
    };
    let pool = PgPool::connect(&url).await?;
    let (org, kb) = seed(&pool).await?;
    let provenance = serde_json::json!({"evidence_id":"splunk:NOTABLE-1"});
    fn make_registration<'a>(
        kb_id: Uuid,
        provenance: &'a serde_json::Value,
        canonical_key: &'a str,
    ) -> Registration<'a> {
        Registration {
            kb_id,
            tenant_id: "tenant-a",
            entity_type: "SplunkNotable",
            source_system: "splunk",
            source_instance: "prod",
            source_identifier: "NOTABLE-1",
            canonical_key,
            status: "active",
            source_revision_id: Some("1"),
            observed_at: Utc::now(),
            provenance,
        }
    }

    let (left, right) = tokio::join!(
        soorin_identity::register(&pool, make_registration(kb, &provenance, "soorin:splunknotable:one")),
        soorin_identity::register(&pool, make_registration(kb, &provenance, "soorin:splunknotable:one")),
    );
    let left = left?;
    let right = right?;
    let ids = [left, right].map(|outcome| match outcome {
        RegistrationOutcome::Resolved {
            identity_id,
            authority_id,
        } => (identity_id, authority_id),
        RegistrationOutcome::Conflict { .. } => {
            panic!("equal concurrent registrations cannot conflict")
        }
    });
    assert_eq!(ids[0], ids[1]);

    let conflict = soorin_identity::register(&pool, make_registration(kb, &provenance, "soorin:splunknotable:different")).await?;
    assert!(matches!(conflict, RegistrationOutcome::Conflict { .. }));
    let (count,): (i64,) = sqlx::query_as(
        "SELECT count(*) FROM soorin_identity_conflicts WHERE kb_id=$1 AND resolved_at IS NULL",
    )
    .bind(kb)
    .fetch_one(&pool)
    .await?;
    assert_eq!(count, 1);
    let (status,): (String,) = sqlx::query_as(
        "SELECT status FROM soorin_canonical_identities
          WHERE kb_id=$1 AND canonical_key='soorin:splunknotable:different'",
    )
    .bind(kb)
    .fetch_one(&pool)
    .await?;
    assert_eq!(status, "ambiguous");

    let other_tenant = soorin_identity::register(
        &pool,
        Registration {
            kb_id: kb,
            tenant_id: "tenant-b",
            entity_type: "SplunkNotable",
            source_system: "splunk",
            source_instance: "prod",
            source_identifier: "NOTABLE-TENANT-B",
            canonical_key: "soorin:splunknotable:tenant-b",
            status: "active",
            source_revision_id: Some("1"),
            observed_at: Utc::now(),
            provenance: &provenance,
        },
    )
    .await?;
    let other_tenant_id = match other_tenant {
        RegistrationOutcome::Resolved { identity_id, .. } => identity_id,
        RegistrationOutcome::Conflict { .. } => panic!("new tenant authority cannot conflict"),
    };
    assert!(sqlx::query(
        "INSERT INTO soorin_identity_conflicts
             (id,kb_id,authority_id,existing_identity_id,candidate_identity_id,
              tenant_id,entity_type,reason,provenance,first_seen_at,last_seen_at)
         VALUES ($1,$2,$3,$4,$5,'tenant-a','SplunkNotable','test-cross-tenant','{}',now(),now())",
    )
    .bind(Uuid::now_v7())
    .bind(kb)
    .bind(ids[0].1)
    .bind(ids[0].0)
    .bind(other_tenant_id)
    .execute(&pool)
    .await
    .is_err());

    let (observations, occurrences): (i64, i64) = sqlx::query_as(
        "SELECT count(*), sum(occurrence_count)::bigint
           FROM soorin_identity_observations WHERE kb_id=$1",
    )
    .bind(kb)
    .fetch_one(&pool)
    .await?;
    assert_eq!((observations, occurrences), (2, 3));

    sqlx::query("DELETE FROM organizations WHERE id=$1")
        .bind(org)
        .execute(&pool)
        .await?;
    pool.close().await;
    Ok(())
}

#[tokio::test]
async fn alias_history_is_append_only_and_exact_replay_is_counted() -> anyhow::Result<()> {
    let Some(url) = utopia_store::test_db::url() else {
        return Ok(());
    };
    let pool = PgPool::connect(&url).await?;
    let (org, kb) = seed(&pool).await?;
    let provenance = serde_json::json!({"evidence_id":"splunk:NOTABLE-2"});
    let outcome = soorin_identity::register(
        &pool,
        Registration {
            kb_id: kb,
            tenant_id: "tenant-a",
            entity_type: "Host",
            source_system: "splunk",
            source_instance: "prod",
            source_identifier: "dc01",
            canonical_key: "soorin:host:dc01",
            status: "active",
            source_revision_id: Some("1"),
            observed_at: Utc::now(),
            provenance: &provenance,
        },
    )
    .await?;
    let identity_id = match outcome {
        RegistrationOutcome::Resolved { identity_id, .. } => identity_id,
        RegistrationOutcome::Conflict { .. } => panic!("first registration cannot conflict"),
    };
    let first_at = Utc::now();
    let first_id = soorin_identity::record_alias(
        &pool,
        kb,
        identity_id,
        "DC-01",
        "dc-01",
        None,
        None,
        first_at,
        &provenance,
    )
    .await?;
    let second_id = soorin_identity::record_alias(
        &pool,
        kb,
        identity_id,
        "DC-01",
        "dc-01",
        None,
        None,
        first_at + chrono::Duration::seconds(5),
        &provenance,
    )
    .await?;
    assert_eq!(first_id, second_id);
    let other_provenance = serde_json::json!({"evidence_id":"splunk:NOTABLE-3"});
    let third_id = soorin_identity::record_alias(
        &pool,
        kb,
        identity_id,
        "DC-01",
        "dc-01",
        None,
        None,
        first_at + chrono::Duration::seconds(10),
        &other_provenance,
    )
    .await?;
    assert_ne!(first_id, third_id);
    let rows: Vec<(Uuid, i64, serde_json::Value)> = sqlx::query_as(
        "SELECT id, occurrence_count, provenance FROM soorin_identity_aliases
          WHERE kb_id=$1 AND identity_id=$2 ORDER BY first_seen_at",
    )
    .bind(kb)
    .bind(identity_id)
    .fetch_all(&pool)
    .await?;
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].1, 2);
    assert_eq!(rows[0].2, provenance);

    let (other_org, other_kb) = seed(&pool).await?;
    assert!(
        sqlx::query("UPDATE soorin_identity_authorities SET kb_id=$1 WHERE identity_id=$2",)
            .bind(other_kb)
            .bind(identity_id)
            .execute(&pool)
            .await
            .is_err()
    );
    assert!(soorin_identity::record_alias(
        &pool,
        other_kb,
        identity_id,
        "wrong-kb",
        "wrong-kb",
        None,
        None,
        Utc::now(),
        &provenance,
    )
    .await
    .is_err());

    sqlx::query("DELETE FROM organizations WHERE id IN ($1,$2)")
        .bind(org)
        .bind(other_org)
        .execute(&pool)
        .await?;
    pool.close().await;
    Ok(())
}

#[tokio::test]
async fn utopia_entity_link_is_same_kb_compare_and_set() -> anyhow::Result<()> {
    let Some(url) = utopia_store::test_db::url() else {
        return Ok(());
    };
    let pool = PgPool::connect(&url).await?;
    let (org, kb) = seed(&pool).await?;
    let (other_org, other_kb) = seed(&pool).await?;
    let provenance = serde_json::json!({"evidence_id":"splunk:NOTABLE-4"});
    let outcome = soorin_identity::register(
        &pool,
        Registration {
            kb_id: kb,
            tenant_id: "tenant-a",
            entity_type: "Host",
            source_system: "splunk",
            source_instance: "prod",
            source_identifier: "dc02",
            canonical_key: "soorin:host:dc02",
            status: "active",
            source_revision_id: Some("1"),
            observed_at: Utc::now(),
            provenance: &provenance,
        },
    )
    .await?;
    let identity_id = match outcome {
        RegistrationOutcome::Resolved { identity_id, .. } => identity_id,
        RegistrationOutcome::Conflict { .. } => panic!("first registration cannot conflict"),
    };
    let (entity, other_entity, replacement) = (Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7());
    for (id, entity_kb, name) in [
        (entity, kb, "dc02"),
        (replacement, kb, "dc02-replacement"),
        (other_entity, other_kb, "dc02-other-kb"),
    ] {
        sqlx::query("INSERT INTO entities (id,kb_id,canonical_name) VALUES ($1,$2,$3)")
            .bind(id)
            .bind(entity_kb)
            .bind(name)
            .execute(&pool)
            .await?;
    }
    soorin_identity::link_utopia_entity(&pool, kb, identity_id, entity).await?;
    soorin_identity::link_utopia_entity(&pool, kb, identity_id, entity).await?;
    assert!(
        soorin_identity::link_utopia_entity(&pool, kb, identity_id, replacement)
            .await
            .is_err()
    );
    assert!(
        soorin_identity::link_utopia_entity(&pool, kb, identity_id, other_entity)
            .await
            .is_err()
    );

    sqlx::query("DELETE FROM organizations WHERE id IN ($1,$2)")
        .bind(org)
        .bind(other_org)
        .execute(&pool)
        .await?;
    pool.close().await;
    Ok(())
}
