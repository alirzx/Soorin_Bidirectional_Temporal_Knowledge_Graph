use chrono::Utc;
use sqlx::PgPool;
use utopia_store::soorin_identity::{self, Registration, RegistrationOutcome};
use uuid::Uuid;

async fn seed(pool: &PgPool) -> anyhow::Result<(Uuid, Uuid)> {
    let (org, workspace, kb) = (Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7());
    sqlx::query("INSERT INTO organizations (id,name) VALUES ($1,'soorin-identity-test')")
        .bind(org).execute(pool).await?;
    sqlx::query("INSERT INTO workspaces (id,org_id,name) VALUES ($1,$2,'soorin-identity-test')")
        .bind(workspace).bind(org).execute(pool).await?;
    sqlx::query("INSERT INTO knowledge_bases (id,workspace_id,name) VALUES ($1,$2,'soorin-identity-test')")
        .bind(kb).bind(workspace).execute(pool).await?;
    Ok((org, kb))
}

#[tokio::test]
async fn concurrent_authority_registration_is_idempotent_and_conflicts_are_audited() -> anyhow::Result<()> {
    let Some(url) = utopia_store::test_db::url() else { return Ok(()); };
    let pool = PgPool::connect(&url).await?;
    let (org, kb) = seed(&pool).await?;
    let provenance = serde_json::json!({"evidence_id":"splunk:NOTABLE-1"});
    let make = |canonical_key: &str| Registration {
        kb_id: kb, tenant_id: "tenant-a", entity_type: "SplunkNotable",
        source_system: "splunk", source_instance: "prod", source_identifier: "NOTABLE-1",
        canonical_key, status: "active", source_revision_id: Some("1"),
        observed_at: Utc::now(), provenance: &provenance,
    };

    let (left, right) = tokio::join!(
        soorin_identity::register(&pool, make("soorin:splunknotable:one")),
        soorin_identity::register(&pool, make("soorin:splunknotable:one")),
    );
    let left = left?;
    let right = right?;
    let ids = [left, right].map(|outcome| match outcome {
        RegistrationOutcome::Resolved { identity_id, authority_id } => (identity_id, authority_id),
        RegistrationOutcome::Conflict { .. } => panic!("equal concurrent registrations cannot conflict"),
    });
    assert_eq!(ids[0], ids[1]);

    let conflict = soorin_identity::register(&pool, make("soorin:splunknotable:different")).await?;
    assert!(matches!(conflict, RegistrationOutcome::Conflict { .. }));
    let (count,): (i64,) = sqlx::query_as(
        "SELECT count(*) FROM soorin_identity_conflicts WHERE kb_id=$1 AND resolved_at IS NULL",
    ).bind(kb).fetch_one(&pool).await?;
    assert_eq!(count, 1);

    sqlx::query("DELETE FROM organizations WHERE id=$1").bind(org).execute(&pool).await?;
    pool.close().await;
    Ok(())
}
