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
    crate::pipeline::process_document(&state, doc).await?;
    crate::extraction::extract_document(&state, doc, Default::default()).await?;
    soc_ingestion::process(&state, id).await?;
    let (status,linked):(String,Option<Uuid>)=sqlx::query_as("SELECT r.status,i.utopia_entity_id FROM soorin_ingestion_receipts r JOIN soorin_canonical_identities i ON i.kb_id=r.kb_id WHERE r.id=$1").bind(id).fetch_one(&pool).await?;
    assert_eq!(status, "bound");
    assert!(linked.is_some());
    let entity_id = linked.unwrap();
    let (pat_view, pat) =
        utopia_store::tokens::issue(&pool, user, "SOC read test", "read", Some(&[kb]), None)
            .await?;
    let search_path = format!("/api/v1/kbs/{kb}/search");
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
    sqlx::query("DELETE FROM jobs WHERE payload->>'kb_id'=$1")
        .bind(kb.to_string())
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
    sqlx::query("DELETE FROM organizations WHERE id=$1")
        .bind(org)
        .execute(&pool)
        .await?;
    Ok(())
}
