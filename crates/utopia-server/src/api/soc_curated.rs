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
    if system != "splunk" {
        return Err(AppError::Validation("unsupported_source_profile".into()).into());
    }
    let raw = String::from_utf8(raw.to_vec())
        .map_err(|_| AppError::Validation("soc_input_must_be_utf8".into()))?;
    let scope = json!({"tenant_id":tenant,"source_system":system,"source_instance":instance});
    let _permit = CAPACITY
        .try_acquire()
        .map_err(|_| AppError::Conflict("soc_normalizer_busy".into()))?;
    let python_root = std::env::var_os("UTOPIA_SOC_PYTHON_ROOT")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            if cfg!(test) {
                std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
            } else {
                std::path::PathBuf::from("/app")
            }
        });
    let result = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        let mut child = tokio::process::Command::new("python3")
            .args(["-S", "-m", "soorin.ops.http_adapter"])
            .env("PYTHONPATH", python_root)
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true)
            .spawn()?;
        let mut stdin = child.stdin.take().unwrap();
        // Envelope is parsed and merged only by Python, preserving duplicate checks.
        let input = json!({"http_body":raw,"scope":scope});
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
        let status = child.wait().await?;
        if status.code() == Some(2) {
            return Ok(Err(AppError::Validation(
                "soc_normalization_failed; invalid profile, scope or record".into(),
            )));
        }
        anyhow::ensure!(status.success(), "soc_normalizer_unavailable");
        let value: Value = serde_json::from_slice(&output)?;
        super::soc_ingestion::validate(&value["canonical_event"])?;
        Ok::<_, anyhow::Error>(Ok(value))
    })
    .await
    .map_err(|_| AppError::Conflict("soc_normalizer_timeout".into()))?;
    result
        .map_err(|_| AppError::Other(anyhow::anyhow!("soc_normalizer_unavailable")))?
        .map_err(Into::into)
}

pub async fn preview(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
    headers: HeaderMap,
    raw: Bytes,
) -> ApiResult<Json<Value>> {
    let mut result = normalize(&state, id, &headers, raw).await?;
    result["supports_acceptance_run"] = json!(true);
    Ok(Json(result))
}

pub async fn ingest(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
    headers: HeaderMap,
    raw: Bytes,
) -> ApiResult<Json<Value>> {
    let started = std::time::Instant::now();
    let normalized = normalize(&state, id, &headers, raw).await?;
    tracing::debug!(source_id=%id, duration_ms=started.elapsed().as_millis(), "soc.normalized");
    super::soc_ingestion::ingest(
        State(state),
        Path(id),
        headers,
        Json(normalized["canonical_event"].clone()),
    )
    .await
}
