//! One-shot adapter to the existing Python contract. No duplicate normalizer.
use crate::{error::ApiResult, state::AppState};
use axum::{
    body::Bytes,
    extract::{Path, State},
    http::HeaderMap,
    Json,
};
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use utopia_core::AppError;
use uuid::Uuid;

const LIMIT: usize = 1024 * 1024;
static CAPACITY: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(2);

async fn normalize(
    state: &AppState,
    source_id: Uuid,
    headers: &HeaderMap,
    raw: Bytes,
) -> ApiResult<Value> {
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
    if raw.len() > LIMIT {
        return Err(AppError::Validation("soc_input_too_large".into()).into());
    }
    let (tenant, system, instance): (String, String, String) = sqlx::query_as(
        "SELECT tenant_id,source_system,source_instance FROM soorin_kb_tenants WHERE kb_id=$1",
    )
    .bind(source.kb_id)
    .fetch_optional(&state.pool)
    .await?
    .ok_or(AppError::NotFound)?;
    // Preserve original JSON bytes for Python's duplicate-key validation.
    // The public envelope has only profile + record; scope is server supplied.
    let scope = json!({"tenant_id":tenant,"source_system":system,"source_instance":instance});
    let _permit = CAPACITY
        .try_acquire()
        .map_err(|_| AppError::Conflict("soc_normalizer_busy".into()))?;
    let result = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        let mut child = tokio::process::Command::new("python3")
            .args(["-m", "soorin.ops.http_adapter"])
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true)
            .spawn()?;
        let mut stdin = child.stdin.take().unwrap();
        // Envelope is parsed and merged only by Python, preserving duplicate checks.
        let input = json!({"http_body":String::from_utf8(raw.to_vec())?,"scope":scope});
        stdin.write_all(&serde_json::to_vec(&input)?).await?;
        drop(stdin);
        let mut output = Vec::new();
        child
            .stdout
            .take()
            .unwrap()
            .take((LIMIT + 1) as u64)
            .read_to_end(&mut output)
            .await?;
        anyhow::ensure!(output.len() <= LIMIT, "soc_normalizer_output_limit");
        anyhow::ensure!(
            child.wait().await?.success(),
            "soc_normalizer_rejected_input"
        );
        let value: Value = serde_json::from_slice(&output)?;
        super::soc_ingestion::validate(&value["canonical_event"])?;
        Ok::<_, anyhow::Error>(value)
    })
    .await
    .map_err(|_| AppError::Conflict("soc_normalizer_timeout".into()))?;
    result.map_err(|_| {
        AppError::Validation(
            "soc_normalization_failed; verify profile, record and installed Python adapter".into(),
        )
        .into()
    })
}

pub async fn preview(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
    headers: HeaderMap,
    raw: Bytes,
) -> ApiResult<Json<Value>> {
    Ok(Json(normalize(&state, id, &headers, raw).await?))
}

pub async fn ingest(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
    headers: HeaderMap,
    raw: Bytes,
) -> ApiResult<Json<Value>> {
    let normalized = normalize(&state, id, &headers, raw).await?;
    super::soc_ingestion::ingest(
        State(state),
        Path(id),
        headers,
        Json(normalized["canonical_event"].clone()),
    )
    .await
}
