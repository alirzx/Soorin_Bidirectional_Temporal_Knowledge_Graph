use axum::extract::{Path, State};
use axum::Json;
use serde::Deserialize;
use serde_json::json;
use tracing::Instrument;
use utopia_core::models::Role;
use utopia_core::AppError;
use uuid::Uuid;

use super::documents_routes::{require_reader_kb, DocumentReader};
use crate::error::ApiResult;
use crate::retrieval;
use crate::state::AppState;

#[derive(Deserialize)]
pub struct SearchReq {
    pub q: String,
    #[serde(default)]
    pub top_k: Option<usize>,
    /// 记录轴（0019）：按**那一刻库里有的东西**检索。YYYY-MM-DD 或 RFC3339。
    /// 命中的是当时活着的块、当时还没被删的文档
    #[serde(default)]
    pub as_of: Option<String>,
}

pub async fn search(
    State(state): State<AppState>,
    reader: DocumentReader,
    Path(kb_id): Path<Uuid>,
    Json(req): Json<SearchReq>,
) -> ApiResult<Json<serde_json::Value>> {
    let request_id = Uuid::now_v7();
    async move {
        tracing::debug!("search.request_started");
        let started = std::time::Instant::now();
        let q = req.q.trim();
        if q.is_empty() {
            return Err(AppError::invalid("empty_query", "Search query cannot be empty").into());
        }
        if q.chars().count() > 4000 {
            return Err(AppError::invalid(
                "query_too_long",
                "Search supports up to 4000 characters",
            )
            .into());
        }
        require_reader_kb(&state, &reader, kb_id).await?;
        let kb = utopia_store::access::require_kb(&state.pool, &reader.user, kb_id, Role::Viewer)
            .await?;

        tracing::Span::current().record("workspace_id", tracing::field::display(kb.workspace_id));
        tracing::debug!(
            duration_ms = started.elapsed().as_millis(),
            "search.authorization_completed"
        );
        let top_k = req.top_k.unwrap_or(10).min(50);
        let as_of = super::graph_routes::parse_instant("as_of", req.as_of.as_deref())?;
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(
                crate::reranker::deadline_seconds() + retrieval::QUERY_EMBED_SECONDS + 15,
            ),
            retrieval::hybrid_detailed(&state, kb_id, kb.workspace_id, q, top_k, as_of, None),
        )
        .await
        .map_err(|_| anyhow::anyhow!("search_deadline"))??;
        tracing::info!(
            duration_ms = started.elapsed().as_millis(),
            returned = result.chunks.len(),
            "search.request_completed"
        );
        Ok(Json(
            json!({"results":result.chunks,"retrieval":result.metadata,"request_id":request_id}),
        ))
    }
    .instrument(
        tracing::info_span!("search", %request_id, %kb_id, workspace_id=tracing::field::Empty),
    )
    .await
}
