//! Real-database tests for authoritative SOC identity resolution.
//! Uses a dedicated KB on TEST_DATABASE_URL; never point test_db at a user QA database.
use sqlx::PgPool;
use utopia_store::resolution::resolve_curated_canonical;
use uuid::Uuid;

#[tokio::test]
async fn shared_soc_case_keeps_one_typed_entity_across_documents() -> anyhow::Result<()> {
    let Some(url) = utopia_store::test_db::url() else {
        return Ok(());
    };
    let pool = PgPool::connect(&url).await?;
    utopia_store::db::migrate(&pool).await?;

    let (org, ws, kb, kind) = (
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
    );
    sqlx::query("INSERT INTO organizations(id,name) VALUES($1,'soc-canonical-test')")
        .bind(org)
        .execute(&pool)
        .await?;
    sqlx::query("INSERT INTO workspaces(id,org_id,name) VALUES($1,$2,'soc-canonical-test')")
        .bind(ws)
        .bind(org)
        .execute(&pool)
        .await?;
    sqlx::query(
        "INSERT INTO knowledge_bases(id,workspace_id,name) VALUES($1,$2,'soc-canonical-test')",
    )
    .bind(kb)
    .bind(ws)
    .execute(&pool)
    .await?;
    sqlx::query("INSERT INTO entity_types(id,kb_id,key,label) VALUES($1,$2,'soc_case','SOCCase')")
        .bind(kind)
        .bind(kb)
        .execute(&pool)
        .await?;

    let run = async {
        let key = "soorin:soccase:synthetic-shared-case";
        let (a,b) = tokio::join!(
            resolve_curated_canonical(&pool,kb,key,"SOCCase"),
            resolve_curated_canonical(&pool,kb,key,"SOCCase"),
        );
        let a=a?;
        let b=b?;
        anyhow::ensure!(a==b,"parallel receipts created different canonical entities");
        let row:(Option<Uuid>,String)=sqlx::query_as(
            "SELECT type_id, specific_type FROM entities WHERE id=$1")
            .bind(a).fetch_one(&pool).await?;
        anyhow::ensure!(row.0 == Some(kind) && row.1=="SOCCase","canonical type not installed");
        let count:i64=sqlx::query_scalar(
            "SELECT count(*) FROM entities WHERE kb_id=$1 AND canonical_name=$2 AND merged_into IS NULL")
            .bind(kb).bind(key).fetch_one(&pool).await?;
        anyhow::ensure!(count==1,"shared case key has {count} entities, expected one");

        // A different authoritative type is a conflict, not an implicit retag.
        let bad=resolve_curated_canonical(&pool,kb,key,"WrongKind").await;
        anyhow::ensure!(bad.is_err(),"unknown kind was accepted");
        // Regression: no automatic merging of previously corrupted identities.
        let duplicate=Uuid::now_v7();
        sqlx::query("INSERT INTO entities(id,kb_id,canonical_name) VALUES($1,$2,$3)")
            .bind(duplicate).bind(kb).bind(key).execute(&pool).await?;
        let ambiguous=resolve_curated_canonical(&pool,kb,key,"SOCCase").await;
        anyhow::ensure!(ambiguous.is_err(),"ambiguous old identity should require human review");
        Ok::<_,anyhow::Error>(())
    }.await;
    sqlx::query("DELETE FROM organizations WHERE id=$1")
        .bind(org)
        .execute(&pool)
        .await?;
    pool.close().await;
    run
}

#[tokio::test]
async fn reviewed_keys_authority_conflicts_and_human_types_are_deterministic() -> anyhow::Result<()>
{
    let Some(url) = utopia_store::test_db::url() else {
        return Ok(());
    };
    let pool = PgPool::connect(&url).await?;
    let (org, ws, kb) = (Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7());
    sqlx::raw_sql(&format!("INSERT INTO organizations(id,name) VALUES('{org}','soc-key-review');
      INSERT INTO workspaces(id,org_id,name) VALUES('{ws}','{org}','soc-key-review');
      INSERT INTO knowledge_bases(id,workspace_id,name) VALUES('{kb}','{ws}','soc-key-review');
      INSERT INTO soorin_kb_tenants(kb_id,tenant_id,source_system,source_instance) VALUES('{kb}','synthetic-tenant','splunk','test');"))
      .execute(&pool).await?;
    let result: anyhow::Result<()> = async {
        let spec:serde_json::Value=serde_json::from_str(include_str!("../../../soorin/ontology/soc_ontology_v1.yaml"))?;
        for row in spec["entity_types"].as_array().unwrap() {
            sqlx::query("INSERT INTO entity_types(id,kb_id,key,label) VALUES($1,$2,$3,$4)")
                .bind(Uuid::now_v7()).bind(kb).bind(row["key"].as_str()).bind(row["label"].as_str()).execute(&pool).await?;
        }
        // A lookalike display label may not select an unrelated ontology key.
        sqlx::query("INSERT INTO entity_types(id,kb_id,key,label) VALUES($1,$2,'unrelated_case','SOCCase')")
            .bind(Uuid::now_v7()).bind(kb).execute(&pool).await?;
        let expected:Uuid=sqlx::query_scalar("SELECT id FROM entity_types WHERE kb_id=$1 AND key='soc_case'")
            .bind(kb).fetch_one(&pool).await?;
        for kind in ["SOCCase","Host","UserAccount","IPAddress","SplunkNotable","SecurityEvent"] {
            let key=format!("soorin:{}:shared-test",kind.to_lowercase());
            let calls=(0..8).map(|_|resolve_curated_canonical(&pool,kb,&key,kind));
            let mut ids=Vec::new();
            for result in futures_util::future::join_all(calls).await { ids.push(result?); }
            assert!(ids.iter().all(|id|*id==ids[0]));
        }
        let key="soorin:soccase:authority-test";
        let entity=resolve_curated_canonical(&pool,kb,key,"SOCCase").await?;
        let actual:Uuid=sqlx::query_scalar("SELECT type_id FROM entities WHERE id=$1").bind(entity).fetch_one(&pool).await?;
        assert_eq!(actual,expected);
        let outcome=utopia_store::soorin_identity::register(&pool,utopia_store::soorin_identity::Registration {
            kb_id:kb,tenant_id:"synthetic-tenant",entity_type:"SOCCase",source_system:"splunk",source_instance:"test",
            source_identifier:"case-authority",canonical_key:key,status:"active",source_revision_id:None,
            observed_at:chrono::Utc::now(),provenance:&serde_json::json!({"synthetic":true})
        }).await?;
        let identity=match outcome {utopia_store::soorin_identity::RegistrationOutcome::Resolved{identity_id,..}=>identity_id,_=>panic!("unexpected conflict")};
        utopia_store::soorin_identity::link_utopia_entity(&pool,kb,identity,entity).await?;
        sqlx::query("UPDATE entities SET canonical_name='Human display name',type_source='human' WHERE id=$1")
            .bind(entity).execute(&pool).await?;
        assert_eq!(resolve_curated_canonical(&pool,kb,key,"SOCCase").await?,entity);
        // A human's explicitly unset type is a durable review decision.
        sqlx::query("UPDATE entities SET type_id=NULL WHERE id=$1").bind(entity).execute(&pool).await?;
        assert!(resolve_curated_canonical(&pool,kb,key,"SOCCase").await.is_err());
        let after:Option<Uuid>=sqlx::query_scalar("SELECT type_id FROM entities WHERE id=$1").bind(entity).fetch_one(&pool).await?;
        assert!(after.is_none());
        sqlx::query("UPDATE entities SET canonical_name=$2,type_id=$3 WHERE id=$1")
            .bind(entity).bind(key).bind(expected).execute(&pool).await?;
        for _ in 0..9 {
            sqlx::query("INSERT INTO entities(id,kb_id,canonical_name) VALUES($1,$2,$3)")
                .bind(Uuid::now_v7()).bind(kb).bind(key).execute(&pool).await?;
        }
        let binding=utopia_store::resolution::inspect_curated_canonical(&pool,kb,key).await?;
        assert_eq!(binding.conflict,Some("duplicate_live_entities"));
        assert_eq!(binding.candidate_count,10);
        assert_eq!(binding.candidate_ids.len(),8);
        assert!(binding.candidates_truncated && binding.entity_id.is_none());
        assert_eq!(binding.linked_entity_id,Some(entity));
        assert!(resolve_curated_canonical(&pool,kb,key,"SOCCase").await.is_err());
        Ok(())
    }.await;
    sqlx::query("DELETE FROM organizations WHERE id=$1")
        .bind(org)
        .execute(&pool)
        .await?;
    result
}
