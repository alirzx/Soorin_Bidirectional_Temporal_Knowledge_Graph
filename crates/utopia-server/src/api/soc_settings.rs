use crate::{auth::AuthUser, error::ApiResult, state::AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use utopia_core::models::Role;
use uuid::Uuid;

pub async fn get(
    State(state): State<AppState>,
    AuthUser(user): AuthUser,
    Path(workspace): Path<Uuid>,
) -> ApiResult<Json<crate::reranker::Config>> {
    utopia_store::workspaces::require_role(&state.pool, user.id, workspace, Role::Admin).await?;
    Ok(Json(crate::reranker::config(&state.pool, workspace).await?))
}

pub async fn backfill(
    State(state): State<AppState>,
    AuthUser(user): AuthUser,
    Path(workspace): Path<Uuid>,
) -> ApiResult<Json<serde_json::Value>> {
    utopia_store::workspaces::require_role(&state.pool, user.id, workspace, Role::Admin).await?;
    let settings = utopia_store::settings::get(&state.pool, workspace)
        .await?
        .ok_or_else(|| utopia_core::AppError::Validation("embedding_not_configured".into()))?;
    let fingerprint = utopia_store::soorin_embeddings::identity(&settings);
    let docs:Vec<(Uuid,Uuid)>=sqlx::query_as("SELECT DISTINCT c.document_id,c.kb_id FROM chunks c JOIN knowledge_bases k ON k.id=c.kb_id JOIN documents d ON d.id=c.document_id WHERE k.workspace_id=$1 AND d.deleted_at IS NULL AND c.superseded_at IS NULL AND (c.embedding IS NULL OR c.embedding_model IS DISTINCT FROM $2) ORDER BY c.document_id LIMIT 1000")
        .bind(workspace).bind(fingerprint).fetch_all(&state.pool).await?;
    for (document, kb) in &docs {
        utopia_store::jobs::enqueue_unless_queued(
            &state.pool,
            "soc_reembed_document",
            serde_json::json!({"document_id":document,"kb_id":kb}),
        )
        .await?;
    }
    Ok(Json(
        serde_json::json!({"queued":docs.len(),"batch_limit":1000,"repeat_until_zero":true}),
    ))
}
pub async fn put(
    State(state): State<AppState>,
    AuthUser(user): AuthUser,
    Path(workspace): Path<Uuid>,
    Json(config): Json<crate::reranker::Config>,
) -> ApiResult<Json<serde_json::Value>> {
    utopia_store::workspaces::require_role(&state.pool, user.id, workspace, Role::Admin).await?;
    if config.enabled {
        utopia_llm::egress::require(&config.base_url)?;
        if config.model.trim().is_empty() {
            return Err(
                utopia_core::AppError::Validation("reranker model is required".into()).into(),
            );
        }
    }
    sqlx::query("INSERT INTO soorin_workspace_runtime(workspace_id,reranker) VALUES($1,$2) ON CONFLICT(workspace_id) DO UPDATE SET reranker=$2,updated_at=now()")
        .bind(workspace).bind(serde_json::to_value(config).map_err(anyhow::Error::from)?).execute(&state.pool).await?;
    utopia_store::audit::record(
        &state.pool,
        None,
        user.id,
        "settings.reranker",
        "workspace",
        Some(workspace),
        serde_json::json!({"changed":true}),
    )
    .await?;
    Ok(Json(serde_json::json!({"ok":true})))
}
