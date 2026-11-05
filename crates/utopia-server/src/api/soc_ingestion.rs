//! Recoverable SOC ingestion saga using the existing durable Utopia job queue.
//! Registration precedes Statements submission. Binding waits for materialization.
use crate::{auth::AuthUser, error::ApiResult, state::AppState};
use axum::{
    extract::{Path, State},
    http::HeaderMap,
    Json,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use utopia_core::{models::Role, AppError};
use uuid::Uuid;

pub async fn bind_tenant(
    State(state): State<AppState>,
    AuthUser(user): AuthUser,
    Path(kb): Path<Uuid>,
    Json(value): Json<Value>,
) -> ApiResult<Json<Value>> {
    utopia_store::access::require_kb(&state.pool, &user, kb, Role::Admin).await?;
    let tenant = field(&value, "tenant_id")?;
    let system = field(&value, "source_system")?;
    let instance = field(&value, "source_instance")?;
    let result=sqlx::query("INSERT INTO soorin_kb_tenants(kb_id,tenant_id,source_system,source_instance) VALUES($1,$2,$3,$4) ON CONFLICT(kb_id) DO UPDATE SET tenant_id=EXCLUDED.tenant_id WHERE soorin_kb_tenants.tenant_id=EXCLUDED.tenant_id AND soorin_kb_tenants.source_system=EXCLUDED.source_system AND soorin_kb_tenants.source_instance=EXCLUDED.source_instance")
        .bind(kb).bind(tenant).bind(system).bind(instance).execute(&state.pool).await?;
    if result.rows_affected() == 0 {
        return Err(AppError::Conflict("KB tenant/source binding is immutable".into()).into());
    }
    utopia_store::audit::record(
        &state.pool,
        Some(kb),
        user.id,
        "soc.tenant_bound",
        "knowledge_base",
        Some(kb),
        json!({"configured":true}),
    )
    .await?;
    Ok(Json(json!({"ok":true})))
}

fn hex_digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

fn field<'a>(value: &'a Value, key: &str) -> anyhow::Result<&'a str> {
    value[key]
        .as_str()
        .filter(|v| !v.trim().is_empty() && v.chars().count() <= 512)
        .ok_or_else(|| anyhow::anyhow!("invalid SOC field {key}"))
}

pub fn validate(event: &Value) -> anyhow::Result<()> {
    super::soc_event_validation::validate(event)?;
    anyhow::ensure!(
        event["schema_version"] == "soorin.soc.knowledge-event.v1",
        "unsupported_soc_schema"
    );
    anyhow::ensure!(
        event["content_checksum_version"] == "soorin.source-content.sha256.v3",
        "SOC runtime requires checksum v3; historical Statements routes remain available"
    );
    for key in [
        "tenant_id",
        "source_system",
        "source_instance",
        "source_record_id",
        "event_type",
        "event_id",
    ] {
        field(event, key)?;
    }
    for key in ["event_time", "observed_at", "recorded_at"] {
        chrono::DateTime::parse_from_rfc3339(field(event, key)?)?;
    }
    let entities = event["entities"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("entities_required"))?;
    anyhow::ensure!(
        !entities.is_empty() && entities.len() <= 128,
        "invalid_entity_count"
    );
    let mut ids = std::collections::HashSet::new();
    for entity in entities {
        let id = field(entity, "entity_id")?;
        anyhow::ensure!(
            id.starts_with("soorin:") && ids.insert(id),
            "invalid_or_duplicate_canonical_id"
        );
        field(entity, "entity_type")?;
        field(entity, "normalized_value")?;
    }
    for relation in event["relations"].as_array().into_iter().flatten() {
        anyhow::ensure!(
            relation["confidence_category"] != "model_proposed",
            "model proposals require review before ingestion"
        );
        anyhow::ensure!(
            ids.contains(field(relation, "subject_entity_id")?)
                && ids.contains(field(relation, "object_entity_id")?),
            "dangling_relation"
        );
    }
    let mut source = event.clone();
    let source = source
        .as_object_mut()
        .ok_or_else(|| anyhow::anyhow!("event_must_be_object"))?;
    for key in [
        "content_checksum",
        "content_checksum_version",
        "recorded_at",
        "processed_at",
        "delivery_id",
    ] {
        source.remove(key);
    }
    if let Some(facts) = source.get_mut("facts").and_then(Value::as_array_mut) {
        for fact in facts {
            if let Some(row) = fact.as_object_mut() {
                row.remove("recorded_at");
            }
        }
    }
    canonicalize_source(source)?;
    let bytes = format!(
        "soorin.source-content.sha256.v3\0{}",
        python_json(&Value::Object(source.clone()))?
    );
    anyhow::ensure!(
        event["content_checksum"].as_str() == Some(hex_digest(bytes.as_bytes()).as_str()),
        "source_checksum_mismatch"
    );
    Ok(())
}

fn canonicalize_source(source: &mut serde_json::Map<String, Value>) -> anyhow::Result<()> {
    fn time(row: &mut serde_json::Map<String, Value>, key: &str) -> anyhow::Result<()> {
        if let Some(value) = row.get_mut(key) {
            if value.is_null() {
                row.remove(key);
            } else {
                let parsed = chrono::DateTime::parse_from_rfc3339(
                    value
                        .as_str()
                        .ok_or_else(|| anyhow::anyhow!("soc_time_invalid"))?,
                )?;
                *value = json!(parsed
                    .to_utc()
                    .to_rfc3339_opts(chrono::SecondsFormat::Micros, true));
            }
        }
        Ok(())
    }
    fn set(row: &mut serde_json::Map<String, Value>, key: &str) {
        let list = row
            .entry(key)
            .or_insert_with(|| json!([]))
            .as_array_mut()
            .unwrap();
        list.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
        list.dedup();
    }
    for key in ["event_time", "observed_at"] {
        time(source, key)?;
    }
    source.retain(|_, v| !v.is_null());
    for key in ["attributes", "vendor_fields"] {
        source.entry(key).or_insert_with(|| json!({}));
    }
    set(source, "source_references");
    for (collection, id, set_key) in [
        ("entities", "entity_id", "aliases"),
        ("relations", "relation_id", "evidence_ids"),
        ("facts", "fact_id", "evidence_ids"),
        ("evidence", "evidence_id", "source_event_ids"),
    ] {
        let rows = source
            .entry(collection)
            .or_insert_with(|| json!([]))
            .as_array_mut()
            .unwrap();
        for row in rows.iter_mut() {
            let row = row.as_object_mut().unwrap();
            row.retain(|_, v| !v.is_null());
            for key in ["valid_from", "valid_to", "observed_at", "invalidated_at"] {
                time(row, key)?;
            }
            set(row, set_key);
        }
        rows.sort_by(|a, b| a[id].as_str().cmp(&b[id].as_str()));
    }
    Ok(())
}

// v3 uses Python's shortest float spelling, including signed/zero-padded
// exponents. serde_json's numeric exponent spelling differs (1e-7 vs 1e-07).
fn python_json(value: &Value) -> anyhow::Result<String> {
    Ok(match value {
        Value::Array(rows) => format!(
            "[{}]",
            rows.iter()
                .map(python_json)
                .collect::<anyhow::Result<Vec<_>>>()?
                .join(",")
        ),
        Value::Object(row) => format!(
            "{{{}}}",
            row.iter()
                .map(|(key, value)| Ok(format!(
                    "{}:{}",
                    serde_json::to_string(key)?,
                    python_json(value)?
                )))
                .collect::<anyhow::Result<Vec<_>>>()?
                .join(",")
        ),
        Value::Number(number) if number.is_f64() => {
            let raw = number.to_string();
            if let Some((mantissa, exponent)) = raw.split_once('e') {
                let exp: i32 = exponent.parse()?;
                let mantissa = mantissa.strip_suffix(".0").unwrap_or(mantissa);
                if (-4..16).contains(&exp) {
                    let text = number.as_f64().unwrap().to_string();
                    if text.contains('.') {
                        text
                    } else {
                        format!("{text}.0")
                    }
                } else {
                    format!("{mantissa}e{exp:+03}")
                }
            } else if number.as_f64().unwrap().abs() >= 1e16 {
                let negative = raw.starts_with('-');
                let digits = raw.trim_start_matches('-').trim_end_matches(".0");
                let exponent = digits.len() - 1;
                let significant = digits.trim_end_matches('0');
                let mantissa = if significant.len() > 1 {
                    format!("{}.{}", &significant[..1], &significant[1..])
                } else {
                    significant.to_owned()
                };
                format!(
                    "{}{mantissa}e+{exponent:02}",
                    if negative { "-" } else { "" }
                )
            } else {
                raw
            }
        }
        _ => serde_json::to_string(value)?,
    })
}

pub async fn ingest(
    State(state): State<AppState>,
    Path(source_id): Path<Uuid>,
    headers: HeaderMap,
    Json(event): Json<Value>,
) -> ApiResult<Json<Value>> {
    let source = utopia_store::sources::get(&state.pool, source_id).await?;
    let token = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "));
    if source.kind != "statements"
        || !token.is_some_and(|v| {
            super::sources_routes::push_key_matches(source.ingest_token.as_deref(), v)
        })
    {
        return Err(AppError::Unauthorized.into());
    }
    super::soc_event_validation::storage_policy(
        &event,
        std::env::var("UTOPIA_SOC_ALLOW_SENSITIVE_PAYLOAD").as_deref() == Ok("1"),
    )
    .map_err(|_| AppError::Validation("soc_sensitive_payload_policy".into()))?;
    validate(&event).map_err(|_| AppError::Validation("invalid SOC knowledge event".into()))?;
    let legacy_source:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM documents WHERE source_id=$1) AND NOT EXISTS(SELECT 1 FROM soorin_ingestion_receipts WHERE source_id=$1)").bind(source_id).fetch_one(&state.pool).await?;
    if legacy_source {
        return Err(AppError::Conflict("native SOC receipts require a dedicated empty Statements source; preserve existing source documents".into()).into());
    }
    let binding: Option<(String, String, String)> = sqlx::query_as(
        "SELECT tenant_id,source_system,source_instance FROM soorin_kb_tenants WHERE kb_id=$1",
    )
    .bind(source.kb_id)
    .fetch_optional(&state.pool)
    .await?;
    if !binding.is_some_and(|(tenant, system, instance)| {
        event["tenant_id"] == tenant
            && event["source_system"] == system
            && event["source_instance"] == instance
    }) {
        return Err(AppError::NotFound.into());
    }
    let key = serde_json::to_string(&json!([
        event["tenant_id"],
        event["source_system"],
        event["source_instance"],
        event["source_record_id"],
        event["event_type"]
    ]))
    .map_err(anyhow::Error::from)?;
    let mut tx = state.pool.begin().await?;
    let (receipt,status):(Uuid,String)=sqlx::query_as("INSERT INTO soorin_ingestion_receipts(id,kb_id,source_id,source_key,checksum,payload) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(source_id,source_key,checksum) DO UPDATE SET updated_at=now() RETURNING id,status")
        .bind(Uuid::now_v7()).bind(source.kb_id).bind(source_id).bind(key).bind(field(&event,"content_checksum")?).bind(&event).fetch_one(&mut *tx).await?;
    let existing:Option<(i64,String)>=sqlx::query_as("SELECT j.id,j.status FROM jobs j JOIN soorin_ingestion_receipts r ON r.job_id=j.id WHERE r.id=$1").bind(receipt).fetch_optional(&mut *tx).await?;
    let job = if matches!(status.as_str(), "bound" | "quarantined")
        || existing
            .as_ref()
            .is_some_and(|(_, status)| matches!(status.as_str(), "queued" | "running"))
    {
        existing.map(|(id, _)| id)
    } else {
        Some(
            utopia_store::jobs::enqueue_with_max_attempts_tx(
                &mut tx,
                "soc_ingest",
                json!({"receipt_id":receipt,"kb_id":source.kb_id}),
                5,
            )
            .await?,
        )
    };
    sqlx::query("UPDATE soorin_ingestion_receipts SET job_id=$2 WHERE id=$1")
        .bind(receipt)
        .bind(job)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(Json(
        json!({"schema_version":"soorin.ingestion-receipt.v1","receipt_id":receipt,"job_id":job,"status":status}),
    ))
}

fn render(event: &Value) -> anyhow::Result<Value> {
    let mut entities = Vec::new();
    let mut names = Vec::new();
    let mut statements = Vec::new();
    let when = event["event_time"].clone();
    let qualifiers = json!({"tenant_id":event["tenant_id"],"source_system":event["source_system"],"source_instance":event["source_instance"],"source_record_id":event["source_record_id"],"confidence_category":"observed"});
    for entity in event["entities"].as_array().unwrap() {
        entities.push(json!([entity["entity_id"], entity["entity_type"], true]));
        names.push(json!([
            entity["entity_id"],
            entity["normalized_value"],
            null
        ]));
    }
    for relation in event["relations"].as_array().into_iter().flatten() {
        let mut q = qualifiers.clone();
        q["evidence_ids"] = json!(serde_json::to_string(&relation["evidence_ids"])?);
        q["confidence_category"] = relation["confidence_category"].clone();
        statements.push(json!([
            null,
            relation["subject_entity_id"],
            field(relation, "relation_type")?
                .to_lowercase()
                .replace('_', " "),
            relation["object_entity_id"],
            null,
            q,
            relation.get("valid_from").unwrap_or(&when),
            relation.get("valid_to").unwrap_or(&Value::Null)
        ]));
    }
    for fact in event["facts"].as_array().into_iter().flatten() {
        anyhow::ensure!(
            fact["confidence_category"] != "model_proposed",
            "model proposals require review"
        );
        let object = fact.get("object_entity_id").unwrap_or(&Value::Null);
        let literal = if object.is_null() {
            json!(fact["object_value"]
                .as_str()
                .map(String::from)
                .unwrap_or_else(|| fact["object_value"].to_string()))
        } else {
            Value::Null
        };
        let mut q = qualifiers.clone();
        q["evidence_ids"] = json!(serde_json::to_string(&fact["evidence_ids"])?);
        q["confidence_category"] = fact["confidence_category"].clone();
        statements.push(json!([
            null,
            fact["subject_entity_id"],
            field(fact, "predicate")?.to_lowercase().replace('_', " "),
            object,
            literal,
            q,
            fact.get("valid_from").unwrap_or(&when),
            fact.get("valid_to").unwrap_or(&Value::Null)
        ]));
    }
    let anchor = &event["entities"]
        .as_array()
        .unwrap()
        .iter()
        .min_by_key(|entity| match entity["entity_type"].as_str() {
            Some("SecurityAlert") => 0,
            Some("SplunkNotable") => 1,
            Some("SecurityEvent") => 2,
            _ => 10,
        })
        .unwrap()["entity_id"];
    for evidence in event["evidence"].as_array().into_iter().flatten() {
        let seed = format!(
            "{}|{}|{}|{}",
            field(event, "tenant_id")?,
            field(event, "source_system")?,
            field(event, "source_instance")?,
            field(evidence, "evidence_id")?
        );
        let evidence_id = format!("soorin:evidence:{}", hex_digest(seed.as_bytes()));
        entities.push(json!([evidence_id, "EvidenceReference", true]));
        names.push(json!([evidence_id, evidence["evidence_id"], null]));
        statements.push(json!([
            null,
            anchor,
            "supported by",
            evidence_id,
            null,
            qualifiers,
            when,
            null
        ]));
        statements.push(json!([
            null,
            evidence_id,
            "has evidence metadata",
            null,
            serde_json::to_string(evidence)?,
            qualifiers,
            when,
            null
        ]));
    }
    for (predicate, value) in [
        ("has content checksum", event["content_checksum"].clone()),
        ("has source record id", event["source_record_id"].clone()),
        (
            "has structured attributes",
            json!(serde_json::to_string(&event["attributes"])?),
        ),
        (
            "has evidence manifest",
            json!(serde_json::to_string(&event["evidence"])?),
        ),
    ] {
        statements.push(json!([
            null, anchor, predicate, null, value, qualifiers, when, null
        ]));
    }
    let key = serde_json::to_string(&json!([
        event["tenant_id"],
        event["source_system"],
        event["source_instance"],
        event["source_record_id"],
        event["event_type"]
    ]))?;
    let digest = hex_digest(key.as_bytes());
    Ok(
        json!({"external_id":format!("soorin-soc-v2:{}:{}",field(event,"tenant_id")?,&digest[..24]),"doc_time":when,"e":entities,"s":statements,"n":names}),
    )
}

pub async fn process(state: &AppState, id: Uuid) -> anyhow::Result<()> {
    let (kb, source_id, event, status): (Uuid, Uuid, Value, String) = sqlx::query_as(
        "SELECT kb_id,source_id,payload,status FROM soorin_ingestion_receipts WHERE id=$1",
    )
    .bind(id)
    .fetch_one(&state.pool)
    .await?;
    if matches!(status.as_str(), "bound" | "quarantined") {
        return Ok(());
    }
    // Durable short lease: no pool connection is pinned while waiting for a
    // source, and cancellation/crash releases ownership by expiration.
    let owner = Uuid::now_v7();
    let acquired=sqlx::query("INSERT INTO soorin_ingestion_leases(source_id,owner,expires_at) VALUES($1,$2,now()+interval '2 minutes') ON CONFLICT(source_id) DO UPDATE SET owner=$2,expires_at=now()+interval '2 minutes' WHERE soorin_ingestion_leases.expires_at<now()")
        .bind(source_id).bind(owner).execute(&state.pool).await?;
    anyhow::ensure!(acquired.rows_affected() == 1, "soc_source_busy_retry");
    let status: String =
        sqlx::query_scalar("SELECT status FROM soorin_ingestion_receipts WHERE id=$1")
            .bind(id)
            .fetch_one(&state.pool)
            .await?;
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(90),
        process_locked(state, id, kb, source_id, &event, &status),
    )
    .await;
    let _ = sqlx::query("DELETE FROM soorin_ingestion_leases WHERE source_id=$1 AND owner=$2")
        .bind(source_id)
        .bind(owner)
        .execute(&state.pool)
        .await;
    let result = result.unwrap_or_else(|_| Err(anyhow::anyhow!("soc_ingest_timeout_retry")));
    if let Err(error) = &result {
        let code = if error.to_string().starts_with("soc_materialization_pending") {
            "soc_materialization_pending"
        } else {
            "soc_ingest_retryable_failure"
        };
        let _ = sqlx::query(
            "UPDATE soorin_ingestion_receipts SET failure_code=$2,updated_at=now() WHERE id=$1",
        )
        .bind(id)
        .bind(code)
        .execute(&state.pool)
        .await;
    }
    result
}

fn source_clock_advances(
    incoming: chrono::DateTime<chrono::Utc>,
    previous: Option<chrono::DateTime<chrono::Utc>>,
) -> bool {
    previous.is_none_or(|previous| incoming > previous)
}

async fn process_locked(
    state: &AppState,
    id: Uuid,
    kb: Uuid,
    source_id: Uuid,
    event: &Value,
    status: &str,
) -> anyhow::Result<()> {
    if matches!(status, "bound" | "quarantined") {
        return Ok(());
    }
    // Delivery order is not source order. Opaque revision IDs are identities,
    // not sortable clocks. Equal source clocks with changed content are ambiguous.
    let previous: Option<chrono::DateTime<chrono::Utc>> = sqlx::query_scalar(
        "SELECT (payload->>'observed_at')::timestamptz FROM soorin_ingestion_receipts
         WHERE source_id=$1 AND source_key=(SELECT source_key FROM soorin_ingestion_receipts WHERE id=$2)
           AND id<>$2 AND status IN ('submitted','bound')
         ORDER BY (payload->>'observed_at')::timestamptz DESC LIMIT 1",
    ).bind(source_id).bind(id).fetch_optional(&state.pool).await?;
    let observed = chrono::DateTime::parse_from_rfc3339(field(event, "observed_at")?)?.to_utc();
    if !source_clock_advances(observed, previous) {
        sqlx::query("UPDATE soorin_ingestion_receipts SET status='quarantined',failure_code='late_or_ambiguous_revision_retained_for_review',updated_at=now() WHERE id=$1").bind(id).execute(&state.pool).await?;
        return Ok(());
    }
    if status == "pending" {
        for entity in event["entities"].as_array().unwrap() {
            for (authority_name, authority) in entity["source_identifiers"]
                .as_object()
                .into_iter()
                .flat_map(|m| m.iter())
            {
                let authority_key = format!(
                    "authority-v1:{}",
                    serde_json::to_string(&json!([
                        authority_name,
                        authority,
                        entity.get("scope").unwrap_or(&Value::Null)
                    ]))?
                );
                let outcome = utopia_store::soorin_identity::register(
                    &state.pool,
                    utopia_store::soorin_identity::Registration {
                        kb_id: kb,
                        tenant_id: field(event, "tenant_id")?,
                        entity_type: field(entity, "entity_type")?,
                        source_system: field(event, "source_system")?,
                        source_instance: field(event, "source_instance")?,
                        source_identifier: &authority_key,
                        canonical_key: field(entity, "entity_id")?,
                        status: "active",
                        source_revision_id: event["source_revision_id"].as_str(),
                        observed_at: chrono::DateTime::parse_from_rfc3339(field(
                            event,
                            "observed_at",
                        )?)?
                        .with_timezone(&chrono::Utc),
                        provenance: &json!({"receipt_id":id,"checksum":event["content_checksum"]}),
                    },
                )
                .await?;
                if matches!(
                    outcome,
                    utopia_store::soorin_identity::RegistrationOutcome::Conflict { .. }
                ) {
                    sqlx::query("UPDATE soorin_ingestion_receipts SET status='quarantined',failure_code='identity_conflict',updated_at=now() WHERE id=$1").bind(id).execute(&state.pool).await?;
                    return Ok(());
                }
                if let utopia_store::soorin_identity::RegistrationOutcome::Resolved {
                    identity_id,
                    ..
                } = outcome
                {
                    let provenance = json!({"receipt_id":id,"checksum":event["content_checksum"]});
                    let mut aliases = vec![field(entity, "normalized_value")?];
                    aliases.extend(
                        entity["aliases"]
                            .as_array()
                            .unwrap()
                            .iter()
                            .filter_map(Value::as_str),
                    );
                    for alias in aliases {
                        utopia_store::soorin_identity::record_alias(
                            &state.pool,
                            kb,
                            identity_id,
                            alias,
                            &alias.to_lowercase(),
                            Some(
                                chrono::DateTime::parse_from_rfc3339(field(event, "event_time")?)?
                                    .to_utc(),
                            ),
                            None,
                            chrono::Utc::now(),
                            &provenance,
                        )
                        .await?;
                    }
                }
            }
        }
        sqlx::query(
            "UPDATE soorin_ingestion_receipts SET status='registered',updated_at=now() WHERE id=$1",
        )
        .bind(id)
        .execute(&state.pool)
        .await?;
    }
    if status != "submitted" {
        let payload = render(event)?;
        let source = utopia_store::sources::get(&state.pool, source_id).await?;
        super::sources_routes::handle_statements_push(
            state,
            &source,
            &serde_json::to_vec(&payload)?,
        )
        .await
        .map_err(|_| anyhow::anyhow!("soc_statements_submission_failed"))?;
        sqlx::query(
            "UPDATE soorin_ingestion_receipts SET status='submitted',updated_at=now() WHERE id=$1",
        )
        .bind(id)
        .execute(&state.pool)
        .await?;
    }
    let mut missing = false;
    let keys: Vec<&str> = event["entities"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|e| e["entity_id"].as_str())
        .collect();
    let identities:Vec<(Uuid,String)>=sqlx::query_as("SELECT id,canonical_key FROM soorin_canonical_identities WHERE kb_id=$1 AND canonical_key=ANY($2) AND utopia_entity_id IS NULL AND status='active'").bind(kb).bind(keys).fetch_all(&state.pool).await?;
    for (identity, key) in identities {
        let entity:Option<(Uuid,)>=sqlx::query_as("SELECT id FROM entities WHERE kb_id=$1 AND canonical_name=$2 AND merged_into IS NULL LIMIT 1").bind(kb).bind(key).fetch_optional(&state.pool).await?;
        if let Some((entity,)) = entity {
            utopia_store::soorin_identity::link_utopia_entity(&state.pool, kb, identity, entity)
                .await?;
        } else {
            missing = true;
        }
    }
    if missing {
        anyhow::bail!("soc_materialization_pending; receipt remains submitted for retry");
    }
    let payload = render(event)?;
    let key = format!("statements:{}", field(&payload, "external_id")?);
    let ready:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM documents WHERE source_id=$1 AND external_key=$2 AND deleted_at IS NULL AND status='ready' AND graph_status='done')").bind(source_id).bind(&key).fetch_one(&state.pool).await?;
    anyhow::ensure!(
        ready,
        "soc_materialization_pending; receipt remains submitted for retry"
    );
    // Open graph completion alone does not prove reviewed SOC relations were
    // materialized. Human-rejected/unknown bindings are never auto-approved here.
    let ontology: Value = serde_json::from_str(include_str!(
        "../../../../soorin/ontology/soc_ontology_v1.yaml"
    ))?;
    for relation in event["relations"].as_array().into_iter().flatten() {
        let token = |value: &str| {
            value
                .chars()
                .filter(|c| c.is_ascii_alphanumeric())
                .flat_map(char::to_lowercase)
                .collect::<String>()
        };
        let Some(kind) = ontology["relation_types"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| {
                token(row["key"].as_str().unwrap())
                    == token(relation["relation_type"].as_str().unwrap())
            })
        else {
            continue;
        };
        let typed: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM facts f
             JOIN relation_types p ON p.id=f.predicate_id
             JOIN entities s ON s.id=f.subject_id JOIN entities o ON o.id=f.object_id
             JOIN fact_evidence fe ON fe.fact_id=f.id
             JOIN documents d ON d.id=fe.document_id
             WHERE f.kb_id=$1 AND f.invalidated_at IS NULL AND p.key=$2
               AND s.canonical_name=$3 AND o.canonical_name=$4
               AND d.source_id=$5 AND d.external_key=$6 AND d.deleted_at IS NULL)",
        )
        .bind(kb)
        .bind(kind["key"].as_str().unwrap())
        .bind(relation["subject_entity_id"].as_str().unwrap())
        .bind(relation["object_entity_id"].as_str().unwrap())
        .bind(source_id)
        .bind(&key)
        .fetch_one(&state.pool)
        .await?;
        anyhow::ensure!(
            typed,
            "soc_materialization_pending; reviewed SOC relation not materialized"
        );
    }
    sqlx::query("UPDATE soorin_ingestion_receipts SET status='bound',failure_code=NULL,updated_at=now() WHERE id=$1")
        .bind(id)
        .execute(&state.pool)
        .await?;
    Ok(())
}

/// Payload-free operator diagnostics, protected by KB administration.
pub async fn receipts(
    State(state): State<AppState>,
    AuthUser(user): AuthUser,
    Path(kb): Path<Uuid>,
) -> ApiResult<Json<Value>> {
    utopia_store::access::require_kb(&state.pool, &user, kb, Role::Admin).await?;
    let rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('receipt_id',r.id,'source_id',r.source_id,'status',r.status,'failure_code',r.failure_code,'created_at',r.created_at,'updated_at',r.updated_at,'job_id',r.job_id,'job_status',j.status,'attempts',j.attempts,'max_attempts',j.max_attempts,'age_seconds',extract(epoch from now()-r.created_at)) FROM soorin_ingestion_receipts r LEFT JOIN jobs j ON j.id=r.job_id WHERE r.kb_id=$1 ORDER BY r.created_at DESC LIMIT 100").bind(kb).fetch_all(&state.pool).await?;
    let counts:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('status',status,'count',count(*)) FROM soorin_ingestion_receipts WHERE kb_id=$1 GROUP BY status ORDER BY status").bind(kb).fetch_all(&state.pool).await?;
    Ok(Json(
        json!({"schema_version":"soorin.ingestion-status.v1","counts":counts,"receipts":rows,"limit":100}),
    ))
}

pub async fn retry(
    State(state): State<AppState>,
    AuthUser(user): AuthUser,
    Path((kb, id)): Path<(Uuid, Uuid)>,
) -> ApiResult<Json<Value>> {
    utopia_store::access::require_kb(&state.pool, &user, kb, Role::Admin).await?;
    let mut tx = state.pool.begin().await?;
    let row: Option<(String, Option<i64>)> = sqlx::query_as(
        "SELECT status,job_id FROM soorin_ingestion_receipts WHERE kb_id=$1 AND id=$2 FOR UPDATE",
    )
    .bind(kb)
    .bind(id)
    .fetch_optional(&mut *tx)
    .await?;
    let (status, previous) = row.ok_or(AppError::NotFound)?;
    if matches!(status.as_str(), "bound" | "quarantined") {
        return Err(AppError::Conflict(
            "receipt is terminal; quarantine requires identity/revision review".into(),
        )
        .into());
    }
    let pending: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM jobs WHERE id=$1 AND status IN ('queued','running'))",
    )
    .bind(previous)
    .fetch_one(&mut *tx)
    .await?;
    let job = if pending {
        previous.unwrap()
    } else {
        utopia_store::jobs::enqueue_with_max_attempts_tx(
            &mut tx,
            "soc_ingest",
            json!({"receipt_id":id,"kb_id":kb}),
            5,
        )
        .await?
    };
    sqlx::query("UPDATE soorin_ingestion_receipts SET job_id=$2,failure_code=NULL,updated_at=now() WHERE id=$1").bind(id).bind(job).execute(&mut *tx).await?;
    tx.commit().await?;
    utopia_store::audit::record(
        &state.pool,
        Some(kb),
        user.id,
        "soc.receipt_retried",
        "receipt",
        Some(id),
        json!({"job_id":job}),
    )
    .await?;
    Ok(Json(json!({"receipt_id":id,"job_id":job})))
}

#[cfg(test)]
mod rendering_tests {
    use super::*;
    #[test]
    fn revision_order_uses_source_clock_not_delivery_or_offset_spelling() {
        let instant = |value: &str| {
            chrono::DateTime::parse_from_rfc3339(value)
                .unwrap()
                .to_utc()
        };
        let previous = instant("2026-11-05T10:00:00Z");
        assert!(source_clock_advances(previous, None));
        assert!(!source_clock_advances(
            instant("2026-11-05T13:30:00+03:30"),
            Some(previous)
        ));
        assert!(!source_clock_advances(
            instant("2026-11-05T09:59:59Z"),
            Some(previous)
        ));
        assert!(source_clock_advances(
            instant("2026-11-05T10:00:01Z"),
            Some(previous)
        ));
    }
    #[test]
    fn asserted_fact_is_not_relabelled_as_observed() {
        let mut event: Value = serde_json::from_str::<Value>(include_str!(
            "../../../../soorin/tests/fixtures/soc_canonical_minimal_v1.json"
        ))
        .unwrap()["event"]
            .clone();
        event["facts"] = json!([{"subject_entity_id":event["entities"][0]["entity_id"],"predicate":"analyst verdict","object_value":"needs_review","confidence_category":"asserted","evidence_ids":[]}]);
        let rendered = render(&event).unwrap();
        let fact = rendered["s"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row[2] == "analyst verdict")
            .unwrap();
        assert_eq!(fact[5]["confidence_category"], "asserted");
    }
}
