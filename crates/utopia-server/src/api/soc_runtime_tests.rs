//! Real DB/API tests: never run against a user knowledge base.
use super::*;
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

fn fixture() -> Value {
    serde_json::from_str::<Value>(include_str!(
        "../../../../soorin/tests/fixtures/soc_canonical_minimal_v1.json"
    ))
    .unwrap()["event"]
        .clone()
}

#[test]
fn python_checksum_is_verified_before_any_registration() {
    let mut event = fixture();
    soc_ingestion::validate(&event).unwrap();
    event["tenant_id"] = json!("other-tenant");
    assert!(soc_ingestion::validate(&event).is_err());
}

#[test]
fn canonical_python_vectors_and_nested_contract_validation() {
    let vectors: Value = serde_json::from_str(include_str!(
        "../../../../soorin/tests/fixtures/soc_checksum_vectors_v3.json"
    ))
    .unwrap();
    for row in vectors["cases"].as_array().unwrap() {
        soc_ingestion::validate(&row["event"]).unwrap_or_else(|e| panic!("{}: {e}", row["name"]));
    }
    for (key, bad) in [
        ("relations", json!({})),
        ("facts", json!(false)),
        ("evidence", json!("bad")),
        ("source_references", json!({})),
        ("attributes", json!([])),
    ] {
        let mut event = fixture();
        event[key] = bad;
        assert!(
            super::soc_event_validation::validate(&event).is_err(),
            "{key}"
        );
    }
    for (key, bad) in [
        ("source_identifiers", json!({"alert_id":false})),
        ("aliases", json!("bad")),
        ("provisional", json!("false")),
        ("entity_type", json!("Unknown")),
    ] {
        let mut event = fixture();
        event["entities"][0][key] = bad;
        assert!(
            super::soc_event_validation::validate(&event).is_err(),
            "{key}"
        );
    }
    let mut event = fixture();
    event["facts"] = json!([{"fact_id":"f","subject_entity_id":"soorin:securityalert:test","predicate":"has status","object_value":"open","recorded_at":"2026-11-05T00:00:00Z","evidence_ids":["missing"],"confidence_category":"observed"}]);
    assert!(super::soc_event_validation::validate(&event).is_err());
    event["facts"][0]["evidence_ids"] = json!([]);
    assert!(super::soc_event_validation::validate(&event).is_ok());
    event["facts"][0]["confidence_category"] = json!("model_proposed");
    assert!(super::soc_event_validation::validate(&event).is_err());
    event["facts"][0]["confidence_category"] = json!("observed");
    event["facts"][0]["valid_from"] = json!("2026-11-06T00:00:00Z");
    event["facts"][0]["valid_to"] = json!("2026-11-05T00:00:00Z");
    assert!(super::soc_event_validation::validate(&event).is_err());
}

async fn install_soc_ontology(pool: &sqlx::PgPool, kb: Uuid) -> anyhow::Result<()> {
    let ontology: Value = serde_json::from_str(include_str!(
        "../../../../soorin/ontology/soc_ontology_v1.yaml"
    ))?;
    let mut types = std::collections::HashMap::new();
    for row in ontology["entity_types"].as_array().unwrap() {
        let id = Uuid::now_v7();
        let key = row["key"].as_str().unwrap();
        sqlx::query("INSERT INTO entity_types(id,kb_id,key,label) VALUES($1,$2,$3,$4)")
            .bind(id)
            .bind(kb)
            .bind(key)
            .bind(row["label"].as_str())
            .execute(pool)
            .await?;
        types.insert(key.to_string(), id);
    }
    for row in ontology["relation_types"].as_array().unwrap() {
        let id = Uuid::now_v7();
        sqlx::query(
            "INSERT INTO relation_types(id,kb_id,key,label,temporal) VALUES($1,$2,$3,$4,$5)",
        )
        .bind(id)
        .bind(kb)
        .bind(row["key"].as_str())
        .bind(row["label"].as_str())
        .bind(row["temporal"].as_str())
        .execute(pool)
        .await?;
        for key in row["domains"].as_array().unwrap() {
            sqlx::query(
                "INSERT INTO relation_type_domains(relation_type_id,entity_type_id) VALUES($1,$2)",
            )
            .bind(id)
            .bind(types[key.as_str().unwrap()])
            .execute(pool)
            .await?;
        }
        for key in row["ranges"].as_array().unwrap() {
            sqlx::query(
                "INSERT INTO relation_type_ranges(relation_type_id,entity_type_id) VALUES($1,$2)",
            )
            .bind(id)
            .bind(types[key.as_str().unwrap()])
            .execute(pool)
            .await?;
        }
    }
    Ok(())
}

async fn receipt_diagnostic(
    app: Router,
    kb: Uuid,
    id: Uuid,
    token: &str,
) -> anyhow::Result<(u16, Value)> {
    let response = app
        .oneshot(
            Request::get(format!("/api/v1/kbs/{kb}/knowledge/receipts/{id}"))
                .header("authorization", format!("Bearer {token}"))
                .body(Body::empty())?,
        )
        .await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 1024 * 1024).await?;
    Ok((status, serde_json::from_slice(&bytes)?))
}

async fn call(app: Router, path: String, token: &str, body: Value) -> anyhow::Result<(u16, Value)> {
    let response = app
        .oneshot(
            Request::post(path)
                .header("content-type", "application/json")
                .header("authorization", format!("Bearer {token}"))
                .body(Body::from(body.to_string()))?,
        )
        .await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 1024 * 1024).await?;
    Ok((status, serde_json::from_slice(&bytes)?))
}

#[tokio::test]
async fn receipt_replay_materialization_binding_and_tenant_isolation() -> anyhow::Result<()> {
    let Some(url) = utopia_store::test_db::url() else {
        return Ok(());
    };
    let pool = sqlx::PgPool::connect(&url).await?;
    let (org, ws, kb, other_kb, user, source) = (
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
    );
    sqlx::raw_sql(&format!("INSERT INTO organizations(id,name) VALUES('{org}','soc-runtime-test');
      INSERT INTO workspaces(id,org_id,name) VALUES('{ws}','{org}','soc-runtime-test');
      INSERT INTO users(id,org_id,email,display_name,password_hash) VALUES('{user}','{org}','{user}@synthetic.example','test','unused');
      INSERT INTO knowledge_bases(id,workspace_id,name) VALUES('{kb}','{ws}','soc-a'),('{other_kb}','{ws}','soc-b');
      INSERT INTO kb_members(kb_id,user_id,role) VALUES('{kb}','{user}','admin');
      INSERT INTO sources(id,kb_id,kind,name,ingest_token) VALUES('{source}','{kb}','statements','synthetic','synthetic-only-token');
      INSERT INTO soorin_kb_tenants(kb_id,tenant_id,source_system,source_instance) VALUES('{kb}','tenant-blue','splunk','splunk-e2e');"))
      .execute(&pool).await?;
    install_soc_ontology(&pool, kb).await?;
    let dir = tempfile::tempdir()?;
    let cfg = utopia_core::config::AppConfig {
        data_dir: dir.path().to_string_lossy().into_owned(),
        ..Default::default()
    };
    let search = std::sync::Arc::new(utopia_search::SearchIndex::open(
        &dir.path().join("search"),
    )?);
    let state = AppState::new(pool.clone(), &cfg, search, "test-only".into());
    let app = router(state.clone(), &cfg);
    let session = crate::auth::issue_token(&state, user)?;
    // Source boundaries protect established provisional v1 keys, which omit
    // source namespace when no authority exists. Rebinding may not mix scopes.
    let response = app.clone().oneshot(Request::put(format!("/api/v1/kbs/{kb}/knowledge/binding"))
        .header("content-type", "application/json").header("authorization", format!("Bearer {session}"))
        .body(Body::from(json!({"tenant_id":"tenant-blue","source_system":"edr","source_instance":"another-source"}).to_string()))?).await?;
    assert_eq!(response.status().as_u16(), 409);
    let curated = json!({"profile":"agentic-soc.splunk-curated.v1", "record":{
        "alert_row_id":"synthetic-preview", "event_time":"2026-11-01T10:00:00Z", "host":"host.example"}});
    let preview_path = format!("/api/v1/sources/{source}/soc/preview");
    assert_eq!(
        call(app.clone(), preview_path.clone(), "wrong", curated.clone())
            .await?
            .0,
        401
    );
    let (preview_status, preview) =
        call(app.clone(), preview_path, "synthetic-only-token", curated).await?;
    assert_eq!(preview_status, 200);
    assert_eq!(preview["supports_acceptance_run"], true);
    assert_eq!(preview["persistent_writes"], false);
    assert_eq!(preview["canonical_event"]["tenant_id"], "tenant-blue");
    let receipt_count: i64 =
        sqlx::query_scalar("SELECT count(*) FROM soorin_ingestion_receipts WHERE source_id=$1")
            .bind(source)
            .fetch_one(&pool)
            .await?;
    assert_eq!(receipt_count, 0);
    let event = fixture();
    let path = format!("/api/v1/sources/{source}/knowledge-events");
    assert_eq!(
        call(app.clone(), path.clone(), "wrong", event.clone())
            .await?
            .0,
        401
    );
    let (status, receipt) = call(
        app.clone(),
        path.clone(),
        "synthetic-only-token",
        event.clone(),
    )
    .await?;
    assert_eq!(status, 200, "{receipt}");
    let (status, replay) = call(app.clone(), path, "synthetic-only-token", event).await?;
    assert_eq!(status, 200);
    assert_eq!(receipt["receipt_id"], replay["receipt_id"]);
    assert_eq!(receipt["job_id"], replay["job_id"]);
    assert_eq!(receipt["replayed"], false);
    assert_eq!(replay["replayed"], true);
    let collision = app
        .clone()
        .oneshot(
            Request::post(format!("/api/v1/sources/{source}/knowledge-events"))
                .header("content-type", "application/json")
                .header("authorization", "Bearer synthetic-only-token")
                .header("x-soorin-acceptance-run", Uuid::now_v7().to_string())
                .body(Body::from(fixture().to_string()))?,
        )
        .await?;
    assert_eq!(collision.status().as_u16(), 409);
    let calls = (0..8).map(|_| {
        call(
            app.clone(),
            format!("/api/v1/sources/{source}/knowledge-events"),
            "synthetic-only-token",
            fixture(),
        )
    });
    for result in futures_util::future::join_all(calls).await {
        let (status, value) = result?;
        assert_eq!(status, 200);
        assert_eq!(value["job_id"], receipt["job_id"]);
    }
    let id = receipt["receipt_id"].as_str().unwrap().parse()?;
    // No asynchronous graph yet: durable receipt remains submitted for retry.
    // A competing owner is preserved, and contention does not consume retries.
    let lease_owner = Uuid::now_v7();
    sqlx::query("INSERT INTO soorin_ingestion_leases(source_id,owner,expires_at) VALUES($1,$2,now()+interval '2 minutes')")
        .bind(source).bind(lease_owner).execute(&pool).await?;
    let busy = soc_ingestion::process(&state, id).await.unwrap_err();
    assert!(utopia_core::is_deferred(&busy).is_some());
    let owner: Uuid =
        sqlx::query_scalar("SELECT owner FROM soorin_ingestion_leases WHERE source_id=$1")
            .bind(source)
            .fetch_one(&pool)
            .await?;
    assert_eq!(owner, lease_owner);
    // Crash/cancellation recovery takes over an expired lease.
    sqlx::query("UPDATE soorin_ingestion_leases SET expires_at=now()-interval '1 second' WHERE source_id=$1")
        .bind(source).execute(&pool).await?;
    let pending = soc_ingestion::process(&state, id).await.unwrap_err();
    assert!(utopia_core::is_deferred(&pending).is_some());
    let leased: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM soorin_ingestion_leases WHERE source_id=$1)",
    )
    .bind(source)
    .fetch_one(&pool)
    .await?;
    assert!(!leased);
    let doc: Uuid = sqlx::query_scalar("SELECT id FROM documents WHERE source_id=$1")
        .bind(source)
        .fetch_one(&pool)
        .await?;
    // A historical exhausted child has no persisted classification. Its
    // parent must expose repair and retain the submitted source revision.
    sqlx::query("UPDATE jobs SET status='failed' WHERE kind='process_document' AND payload->>'document_id'=$1")
        .bind(doc.to_string()).execute(&pool).await?;
    utopia_store::documents::set_failed(&pool, doc, "synthetic provider outage").await?;
    sqlx::query("UPDATE jobs SET failure_class='terminal',document_version=(SELECT max(version) FROM document_versions WHERE document_id::text=$1) WHERE kind='process_document' AND payload->>'document_id'=$1")
        .bind(doc.to_string()).execute(&pool).await?;
    let terminal = soc_ingestion::process(&state, id).await.unwrap_err();
    assert!(utopia_core::is_terminal(&terminal));
    sqlx::query("UPDATE jobs SET document_version=0 WHERE kind='process_document' AND payload->>'document_id'=$1").bind(doc.to_string()).execute(&pool).await?;
    assert!(
        utopia_core::is_deferred(&soc_ingestion::process(&state, id).await.unwrap_err()).is_some()
    );
    sqlx::query("UPDATE jobs SET failure_class=NULL WHERE kind='process_document' AND payload->>'document_id'=$1")
        .bind(doc.to_string()).execute(&pool).await?;
    let dependency = soc_ingestion::process(&state, id).await.unwrap_err();
    assert!(
        utopia_core::is_deferred(&dependency).is_some(),
        "{dependency:#}"
    );
    let calls = (0..5).map(|_| {
        call(
            app.clone(),
            format!("/api/v1/kbs/{kb}/knowledge/receipts/{id}/retry"),
            &session,
            json!({}),
        )
    });
    for result in futures_util::future::join_all(calls).await {
        assert_eq!(result?.0, 200);
    }
    let repairs: i64 = sqlx::query_scalar("SELECT count(*) FROM jobs WHERE kind='process_document' AND payload->>'document_id'=$1 AND status='queued'")
        .bind(doc.to_string()).fetch_one(&pool).await?;
    assert_eq!(repairs, 1);
    let provider = wiremock::MockServer::start().await;
    wiremock::Mock::given(wiremock::matchers::method("POST"))
        .respond_with(wiremock::ResponseTemplate::new(429).insert_header("Retry-After", "2"))
        .mount(&provider)
        .await;
    sqlx::query("INSERT INTO llm_settings(workspace_id,embed_base_url,embed_model,embed_dim) VALUES($1,$2,'synthetic',2)")
        .bind(ws).bind(provider.uri()).execute(&pool).await?;
    crate::pipeline::process_document(&state, doc).await?;
    crate::extraction::extract_document(&state, doc, Default::default()).await?;
    crate::soc_alignment::types(&pool, kb).await?;
    crate::soc_alignment::phrases(&pool, kb).await?;
    utopia_store::materialize::materialize(&pool, kb).await?;
    soc_ingestion::process(&state, id).await?;
    let enrichment: utopia_store::jobs::Job = sqlx::query_as(
        "SELECT id,kind,payload,attempts,max_attempts,now() AS locked_at FROM jobs WHERE kind='soc_reembed_document' AND payload->>'document_id'=$1",
    ).bind(doc.to_string()).fetch_one(&pool).await?;
    let unavailable = crate::dispatch(&state, &enrichment).await.unwrap_err();
    assert_eq!(
        utopia_llm::rate_limited(&unavailable).unwrap().retry_after,
        Some(std::time::Duration::from_secs(2))
    );
    let search_path = format!("/api/v1/kbs/{kb}/search");
    let (code, fallback) = call(
        app.clone(),
        search_path.clone(),
        &session,
        json!({"q":"A1"}),
    )
    .await?;
    assert_eq!(code, 200);
    assert_eq!(fallback["retrieval"]["dense_executed"], false);
    assert_eq!(fallback["retrieval"]["lexical_method"], "tantivy_bm25");
    crate::errata::schedule_if_ready(&state, kb).await?;
    let errata_jobs: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM jobs WHERE kind='errata_review' AND payload->>'kb_id'=$1",
    )
    .bind(kb.to_string())
    .fetch_one(&pool)
    .await?;
    assert_eq!(errata_jobs, 0);
    crate::errata::review(&state, kb).await?;
    provider.reset().await;
    wiremock::Mock::given(wiremock::matchers::method("POST"))
        .respond_with(
            wiremock::ResponseTemplate::new(200)
                .set_body_json(json!({"data":[{"index":0,"embedding":[1.0,0.0]}]})),
        )
        .mount(&provider)
        .await;
    crate::dispatch(&state, &enrichment).await?;
    let embedded: i64 = sqlx::query_scalar("SELECT count(*) FROM chunks WHERE document_id=$1 AND superseded_at IS NULL AND embedding IS NOT NULL")
        .bind(doc).fetch_one(&pool).await?;
    assert_eq!(embedded, 1);
    sqlx::query("INSERT INTO memberships(workspace_id,user_id,role) VALUES($1,$2,'admin')")
        .bind(ws)
        .bind(user)
        .execute(&pool)
        .await?;
    let backfill = format!("/api/v1/workspaces/{ws}/settings/embedding/backfill");
    sqlx::query("UPDATE chunks SET embedding='[0,0]'::vector WHERE document_id=$1 AND superseded_at IS NULL")
        .bind(doc)
        .execute(&pool)
        .await?;
    let (first, second) = tokio::join!(
        call(app.clone(), backfill.clone(), &session, json!({})),
        call(app.clone(), backfill.clone(), &session, json!({})),
    );
    for response in [first?, second?] {
        let (code, result) = response;
        assert_eq!(code, 200);
        assert_eq!(result["queued"], 1);
        assert_eq!(result["eligible_documents"], 1);
        assert_eq!(result["new_jobs"], 0);
        assert_eq!(result["already_pending"], 1);
    }
    let queued: i64 = sqlx::query_scalar("SELECT count(*) FROM jobs WHERE kind='soc_reembed_document' AND status='queued' AND payload->>'document_id'=$1")
        .bind(doc.to_string()).fetch_one(&pool).await?;
    assert_eq!(queued, 1);
    crate::dispatch(&state, &enrichment).await?;
    let (code, result) = call(app.clone(), backfill, &session, json!({})).await?;
    assert_eq!(code, 200);
    assert_eq!(result["queued"], 0);
    // A previously completed delivery must be rescheduled after a fingerprint
    // change. Concurrent backfills still insert exactly one new queued job.
    sqlx::query("UPDATE jobs SET status='done' WHERE id=$1")
        .bind(enrichment.id)
        .execute(&pool)
        .await?;
    sqlx::query(
        "UPDATE chunks SET embedding_model='stale' WHERE document_id=$1 AND superseded_at IS NULL",
    )
    .bind(doc)
    .execute(&pool)
    .await?;
    let backfill = format!("/api/v1/workspaces/{ws}/settings/embedding/backfill");
    let (first, second) = tokio::join!(
        call(app.clone(), backfill.clone(), &session, json!({})),
        call(app.clone(), backfill.clone(), &session, json!({})),
    );
    let mut inserted = 0;
    for (code, result) in [first?, second?] {
        assert_eq!(code, 200);
        assert_eq!(result["eligible_documents"], 1);
        inserted += result["new_jobs"].as_u64().unwrap();
    }
    assert_eq!(inserted, 1);
    crate::dispatch(&state, &enrichment).await?;
    sqlx::query("DELETE FROM memberships WHERE workspace_id=$1 AND user_id=$2")
        .bind(ws)
        .bind(user)
        .execute(&pool)
        .await?;
    let (code, recovered) = call(
        app.clone(),
        search_path.clone(),
        &session,
        json!({"q":"A1"}),
    )
    .await?;
    assert_eq!(code, 200);
    assert_eq!(recovered["retrieval"]["dense_executed"], true);
    assert_eq!(recovered["retrieval"]["score_type"], "rank_fusion");
    assert!(recovered["retrieval"]["returned"].as_u64().unwrap() > 0);
    sqlx::query("DELETE FROM llm_settings WHERE workspace_id=$1")
        .bind(ws)
        .execute(&pool)
        .await?;
    let (status,linked):(String,Option<Uuid>)=sqlx::query_as("SELECT r.status,i.utopia_entity_id FROM soorin_ingestion_receipts r JOIN soorin_canonical_identities i ON i.kb_id=r.kb_id WHERE r.id=$1").bind(id).fetch_one(&pool).await?;
    assert_eq!(status, "bound");
    assert!(linked.is_some());
    let entity_id = linked.unwrap();
    let (pat_view, pat) =
        utopia_store::tokens::issue(&pool, user, "SOC read test", "read", Some(&[kb]), None)
            .await?;
    assert_eq!(
        call(app.clone(), search_path.clone(), &pat, json!({"q":"A1"}))
            .await?
            .0,
        200
    );
    assert!(matches!(
        call(
            app.clone(),
            format!("/api/v1/kbs/{other_kb}/search"),
            &pat,
            json!({"q":"A1"})
        )
        .await?
        .0,
        403 | 404
    ));
    utopia_store::tokens::revoke(&pool, user, pat_view.id).await?;
    assert_eq!(
        call(app.clone(), search_path, &pat, json!({"q":"A1"}))
            .await?
            .0,
        401
    );

    let resolve_path = format!("/api/v1/kbs/{kb}/knowledge/resolve");
    let authority = json!({"tenant_id":"tenant-blue","source_system":"splunk","source_instance":"splunk-e2e",
        "entity_type":"SecurityAlert","authority_name":"alert_id","source_identifier":"A1"});
    let (status, resolution) = call(
        app.clone(),
        resolve_path.clone(),
        &session,
        authority.clone(),
    )
    .await?;
    assert_eq!(status, 200, "{resolution}");
    assert_eq!(resolution["status"], "resolved", "{resolution}");
    assert_eq!(resolution["candidates"][0]["entity_id"], json!(entity_id));
    for (field, value, expected) in [
        ("tenant_id", "red", 404),
        ("source_instance", "other", 404),
        ("source_identifier", "unknown", 200),
        ("scope", "different-network", 200),
    ] {
        let mut query = authority.clone();
        query[field] = json!(value);
        let (status, result) = call(app.clone(), resolve_path.clone(), &session, query).await?;
        assert_eq!(status, expected);
        if status == 200 {
            assert_eq!(result["status"], "not_found");
        }
    }
    let (status, _) = call(
        app.clone(),
        format!("/api/v1/kbs/{other_kb}/knowledge/resolve"),
        &session,
        authority,
    )
    .await?;
    assert!(matches!(status, 403 | 404));

    let now: chrono::DateTime<chrono::Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&pool)
        .await?;
    let context_path = format!("/api/v1/kbs/{kb}/knowledge/context");
    let historical = json!({"tenant_id":"tenant-blue","entity":entity_id,"as_of":now.to_rfc3339()});
    let (status, old_context) = call(
        app.clone(),
        context_path.clone(),
        &session,
        historical.clone(),
    )
    .await?;
    assert_eq!(status, 200, "{old_context}");
    assert!(!old_context["evidence_references"]
        .as_array()
        .unwrap()
        .is_empty());
    // A later evidence attachment cannot be substituted into the old snapshot.
    sqlx::query("UPDATE fact_evidence SET recorded_at=$2 WHERE fact_id IN (SELECT id FROM facts WHERE kb_id=$1)").bind(kb).bind(now+chrono::Duration::days(1)).execute(&pool).await?;
    let (status, old_context) =
        call(app.clone(), context_path.clone(), &session, historical).await?;
    assert_eq!(status, 200);
    assert_eq!(old_context["retrieval_status"], "partial");
    assert!(old_context["evidence_references"]
        .as_array()
        .unwrap()
        .is_empty());
    let (status, old_entity) = call(
        app.clone(),
        context_path,
        &session,
        json!({"tenant_id":"tenant-blue","entity":entity_id,"as_of":"2000-01-01T00:00:00Z"}),
    )
    .await?;
    assert_eq!(status, 200);
    assert!(old_entity["resolved_entities"]
        .as_array()
        .unwrap()
        .is_empty());
    let (_, replay) = call(
        app.clone(),
        format!("/api/v1/sources/{source}/knowledge-events"),
        "synthetic-only-token",
        fixture(),
    )
    .await?;
    assert_eq!(replay["status"], "bound");
    assert_eq!(replay["job_id"], receipt["job_id"]);
    let query = json!({"tenant_id":"tenant-blue","entity":"A1","limit":10});
    let (status, context) = call(
        app.clone(),
        format!("/api/v1/kbs/{kb}/knowledge/context"),
        &session,
        query.clone(),
    )
    .await?;
    assert_eq!(status, 200, "{context}");
    assert_eq!(context["schema_version"], "soorin.knowledge-context.v2");
    let (status, limited) = call(
        app.clone(),
        format!("/api/v1/kbs/{kb}/knowledge/context"),
        &session,
        json!({"tenant_id":"tenant-blue","entity":"A1","limit":1}),
    )
    .await?;
    assert_eq!(status, 200);
    assert_eq!(limited["bounds"]["returned_count"], 1);
    assert_eq!(limited["bounds"]["truncated"], true);
    assert_eq!(limited["retrieval_status"], "partial");
    let (status, _) = call(
        app.clone(),
        format!("/api/v1/kbs/{other_kb}/knowledge/context"),
        &session,
        query,
    )
    .await?;
    assert!(matches!(status, 403 | 404));
    let (status, _) = call(
        app,
        format!("/api/v1/kbs/{kb}/knowledge/context"),
        &session,
        json!({"tenant_id":"tenant-red","entity":"A1"}),
    )
    .await?;
    assert_eq!(status, 404);
    // Native Search invokes the configured reranker after KB/record filtering.
    let calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let seen = calls.clone();
    let model = axum::Router::new().route(
        "/rerank",
        axum::routing::post(move |Json(body): Json<Value>| {
            let seen = seen.clone();
            async move {
                seen.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                Json(Value::Array(
                    body["texts"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .enumerate()
                        .map(|(i, _)| json!({"index":i,"score":1.0}))
                        .collect(),
                ))
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let base = format!("http://{}", listener.local_addr()?);
    let server = tokio::spawn(async move {
        axum::serve(listener, model).await.unwrap();
    });
    sqlx::query("INSERT INTO soorin_workspace_runtime(workspace_id,reranker) VALUES($1,$2)")
        .bind(ws)
        .bind(json!({"enabled":true,"base_url":base,"model":"synthetic-reranker","fallback":false}))
        .execute(&pool)
        .await?;
    let (status, search) = call(
        router(state.clone(), &cfg),
        format!("/api/v1/kbs/{kb}/search"),
        &session,
        json!({"q":"A1","top_k":5}),
    )
    .await?;
    assert_eq!(status, 200, "{search}");
    assert_eq!(search["retrieval"]["reranker_status"], "complete");
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    server.abort();
    let _ = server.await;
    for (fallback, expected) in [(false, 500), (true, 200)] {
        sqlx::query("UPDATE soorin_workspace_runtime SET reranker=jsonb_set(reranker,'{fallback}',$2) WHERE workspace_id=$1")
            .bind(ws).bind(json!(fallback)).execute(&pool).await?;
        let (status, response) = call(
            router(state.clone(), &cfg),
            format!("/api/v1/kbs/{kb}/search"),
            &session,
            json!({"q":"A1"}),
        )
        .await?;
        assert_eq!(status, expected);
        if fallback {
            assert_eq!(response["retrieval"]["reranker_status"], "fallback");
            assert!(!response["results"].as_array().unwrap().is_empty());
        }
    }
    sqlx::query("DELETE FROM jobs WHERE payload->>'kb_id'=$1 OR payload->>'document_id'=$2")
        .bind(kb.to_string())
        .bind(doc.to_string())
        .execute(&pool)
        .await?;
    // A persisted receipt admitted by an older validator must not silently bind
    // after its unknown relation is skipped. Keep it intact for explicit review.
    let invalid_receipt = Uuid::now_v7();
    let mut invalid = fixture();
    invalid["relations"] = json!([{"relation_id":"legacy-unknown","relation_type":"unknown_relation",
        "subject_entity_id":invalid["entities"][0]["entity_id"],"object_entity_id":invalid["entities"][0]["entity_id"],
        "confidence_category":"observed","evidence_ids":[],"attributes":{}}]);
    sqlx::query("INSERT INTO soorin_ingestion_receipts(id,kb_id,source_id,source_key,checksum,payload) VALUES($1,$2,$3,'legacy-invalid','synthetic',$4)")
        .bind(invalid_receipt).bind(kb).bind(source).bind(&invalid).execute(&pool).await?;
    soc_ingestion::process(&state, invalid_receipt).await?;
    let status: (String, Option<String>) =
        sqlx::query_as("SELECT status,failure_code FROM soorin_ingestion_receipts WHERE id=$1")
            .bind(invalid_receipt)
            .fetch_one(&pool)
            .await?;
    assert_eq!(status.0, "quarantined");
    assert_eq!(status.1.as_deref(), Some("stored_event_requires_review"));
    // Migration 10008 retains ordinary receipts and scopes synthetic pages.
    let run_id = Uuid::now_v7();
    let synthetic_id = Uuid::now_v7();
    sqlx::query("INSERT INTO soorin_ingestion_receipts(id,kb_id,source_id,source_key,checksum,payload,acceptance_run)
        VALUES($1,$2,$3,'synthetic-page','synthetic',$4,$5)")
        .bind(synthetic_id).bind(kb).bind(source).bind(&invalid).bind(run_id)
        .execute(&pool).await?;
    let receipt_path = format!("/api/v1/kbs/{kb}/knowledge/receipts");
    for (suffix, expected) in [("".to_owned(), 3), (format!("?acceptance_run={run_id}"), 1)] {
        let response = router(state.clone(), &cfg)
            .oneshot(
                Request::get(format!("{receipt_path}{suffix}"))
                    .header("authorization", format!("Bearer {session}"))
                    .body(Body::empty())?,
            )
            .await?;
        assert_eq!(response.status().as_u16(), 200);
        let bytes = to_bytes(response.into_body(), 1024 * 1024).await?;
        let result: Value = serde_json::from_slice(&bytes)?;
        let list = result["receipts"].as_array().unwrap();
        assert_eq!(list.len(), expected);
        assert!(list
            .iter()
            .any(|row| row["receipt_id"] == json!(synthetic_id)));
    }
    let app = router(state.clone(), &cfg);
    // The curated ingest route creates the same native receipt and preserves
    // source authentication/checksum idempotency before any graph work.
    let curated = json!({"profile":"agentic-soc.splunk-curated.v1","record":{
        "alert_row_id":"synthetic-http-ingest","event_time":"2026-11-01T10:00:00Z",
        "title":"Password Spray Detection Source Alert","hostname":"http.synthetic.example"}});
    let path = format!("/api/v1/sources/{source}/soc/ingest");
    let (code, first) = call(
        app.clone(),
        path.clone(),
        "synthetic-only-token",
        curated.clone(),
    )
    .await?;
    assert_eq!(code, 200, "{first}");
    let (code, duplicate) = call(app.clone(), path, "synthetic-only-token", curated).await?;
    assert_eq!(code, 200, "{duplicate}");
    assert_eq!(first["receipt_id"], duplicate["receipt_id"]);
    assert_eq!(first["job_id"], duplicate["job_id"]);
    let receipt_id: Uuid = first["receipt_id"].as_str().unwrap().parse()?;
    assert!(utopia_core::is_deferred(
        &soc_ingestion::process(&state, receipt_id)
            .await
            .unwrap_err()
    )
    .is_some());
    let (_, detail) = receipt_diagnostic(app.clone(), kb, receipt_id, &session).await?;
    let document: Uuid = detail["document"]["document_id"]
        .as_str()
        .unwrap()
        .parse()?;
    crate::pipeline::process_document(&state, document).await?;
    let (chunk, text): (Uuid, String) =
        sqlx::query_as("SELECT id,text FROM chunks WHERE document_id=$1 AND superseded_at IS NULL")
            .bind(document)
            .fetch_one(&pool)
            .await?;
    assert!(text.contains("Password Spray Detection Source Alert"));
    let hits = state
        .search
        .search(&kb.to_string(), "password spray detection", 100)?;
    assert!(hits.iter().any(|hit| hit.chunk_id == chunk.to_string()));
    assert!(state
        .search
        .search(&other_kb.to_string(), "password spray detection", 100)?
        .is_empty());
    crate::extraction::extract_document(&state, document, Default::default()).await?;
    crate::soc_alignment::types(&pool, kb).await?;
    crate::soc_alignment::phrases(&pool, kb).await?;
    utopia_store::materialize::materialize(&pool, kb).await?;
    soc_ingestion::process(&state, receipt_id).await?;
    // Full supported relation flow, including a second revision under an
    // already-bound signature. No model/service or global worker is needed.
    let events: Value = serde_json::from_str(include_str!(
        "../../../../soorin/tests/fixtures/soc_native_materialization_v1.json"
    ))?;
    let app = router(state.clone(), &cfg);
    for event in events["events"].as_array().unwrap() {
        let (code, receipt) = call(
            app.clone(),
            format!("/api/v1/sources/{source}/knowledge-events"),
            "synthetic-only-token",
            event.clone(),
        )
        .await?;
        assert_eq!(code, 200, "{receipt}");
        let receipt_id: Uuid = receipt["receipt_id"].as_str().unwrap().parse()?;
        let pending = soc_ingestion::process(&state, receipt_id)
            .await
            .unwrap_err();
        assert!(utopia_core::is_deferred(&pending).is_some());
        let (_, before) = receipt_diagnostic(app.clone(), kb, receipt_id, &session).await?;
        let doc_id: Uuid = before["document"]["document_id"]
            .as_str()
            .unwrap()
            .parse()?;
        crate::pipeline::process_document(&state, doc_id).await?;
        crate::extraction::extract_document(&state, doc_id, Default::default()).await?;
        crate::soc_alignment::types(&pool, kb).await?;
        crate::soc_alignment::phrases(&pool, kb).await?;
        utopia_store::materialize::materialize(&pool, kb).await?;
        soc_ingestion::process(&state, receipt_id).await?;
        let (code, detail) = receipt_diagnostic(app.clone(), kb, receipt_id, &session).await?;
        assert_eq!(code, 200);
        assert_eq!(detail["status"], "bound");
        assert_eq!(
            detail["relations"].as_array().unwrap().len(),
            event["relations"].as_array().unwrap().len()
        );
        for relation in detail["relations"].as_array().unwrap() {
            assert_eq!(relation["binding"]["evidence_link_status"], true);
            assert_eq!(
                relation["binding"]["document_version"],
                detail["document"]["document_version"]
            );
            assert_eq!(relation["binding"]["expected_relation_key"], "observed_on");
        }
        assert!(matches!(
            receipt_diagnostic(app.clone(), other_kb, receipt_id, &session)
                .await?
                .0,
            403 | 404
        ));
    }
    // Historical duplicate rows must be explicit conflicts in diagnostics,
    // never hidden behind LIMIT 1 or allowed to satisfy a typed edge by name.
    let latest = &events["events"][2];
    let alert = latest["entities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entity| entity["entity_type"] == "SecurityAlert")
        .unwrap();
    let key = alert["entity_id"].as_str().unwrap();
    sqlx::query("INSERT INTO entities(id,kb_id,canonical_name) VALUES($1,$2,$3)")
        .bind(Uuid::now_v7())
        .bind(kb)
        .bind(key)
        .execute(&pool)
        .await?;
    let receipt_id: Uuid = sqlx::query_scalar(
        "SELECT id FROM soorin_ingestion_receipts WHERE kb_id=$1 AND payload->>'event_id'=$2",
    )
    .bind(kb)
    .bind(latest["event_id"].as_str())
    .fetch_one(&pool)
    .await?;
    let (_, conflicted) = receipt_diagnostic(app.clone(), kb, receipt_id, &session).await?;
    let entity = conflicted["entities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["canonical_key"] == key)
        .unwrap();
    assert_eq!(entity["identity_conflict"], "duplicate_live_entities");
    assert!(entity["entity_id"].is_null());
    assert_eq!(entity["candidate_count"], 2);
    let (_,resolution)=call(app.clone(),format!("/api/v1/kbs/{kb}/knowledge/resolve"),&session,
        json!({"tenant_id":"tenant-blue","source_system":"splunk","source_instance":"splunk-e2e",
        "entity_type":"SecurityAlert","authority_name":"soc_alert_row_id","source_identifier":"synthetic-B"})).await?;
    assert_eq!(resolution["status"], "ambiguous");
    assert_eq!(resolution["automatic"], false);
    assert!(resolution["candidates"][0]["entity_id"].is_null());
    assert!(conflicted["relations"]
        .as_array()
        .unwrap()
        .iter()
        .any(|r| r["binding"]["evidence_link_status"] == false));
    sqlx::query("DELETE FROM jobs WHERE payload->>'kb_id'=$1 OR payload->>'document_id' IN (SELECT id::text FROM documents WHERE kb_id=$2)")
        .bind(kb.to_string()).bind(kb).execute(&pool).await?;
    sqlx::query("DELETE FROM organizations WHERE id=$1")
        .bind(org)
        .execute(&pool)
        .await?;
    Ok(())
}
