//! Read-only, versioned SOC context over Utopia authorization and temporal graph.
use super::documents_routes::DocumentReader;
use crate::{error::ApiResult, state::AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::Deserialize;
use serde_json::json;
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Query {
    pub tenant_id: String,
    pub entity: String,
    pub entity_type: Option<String>,
    pub at: Option<String>,
    pub as_of: Option<String>,
    pub limit: Option<usize>,
}

pub async fn context(
    State(state): State<AppState>,
    reader: DocumentReader,
    Path(kb): Path<Uuid>,
    Json(query): Json<Query>,
) -> ApiResult<Json<serde_json::Value>> {
    let started = std::time::Instant::now();
    super::documents_routes::require_reader_kb(&state, &reader, kb).await?;
    let binding: Option<(String,)> =
        sqlx::query_as("SELECT tenant_id FROM soorin_kb_tenants WHERE kb_id=$1")
            .bind(kb)
            .fetch_optional(&state.pool)
            .await?;
    if binding.as_ref().map(|r| r.0.as_str()) != Some(query.tenant_id.as_str()) {
        return Err(utopia_core::AppError::NotFound.into());
    }
    if query.entity.trim().is_empty() || query.entity.len() > 512 {
        return Err(
            utopia_core::AppError::Validation("entity must contain 1..512 bytes".into()).into(),
        );
    }
    let at = super::graph_routes::parse_instant("at", query.at.as_deref())?;
    let as_of = super::graph_routes::parse_instant("as_of", query.as_of.as_deref())?;
    let limit = query.limit.unwrap_or(40).clamp(1, 100);
    let (nodes, _) =
        utopia_store::graph::search_entities(&state.pool, kb, &query.entity, 20, 0, as_of).await?;
    let nodes: Vec<_> = nodes
        .into_iter()
        .filter(|n| {
            query
                .entity_type
                .as_deref()
                .is_none_or(|kind| n.type_key.as_deref() == Some(kind))
        })
        .collect();
    let mut facts = Vec::new();
    let mut evidence = Vec::new();
    let mut resolved = Vec::new();
    for node in nodes.into_iter().take(5) {
        let (node, rows) =
            utopia_store::graph::entity_detail(&state.pool, kb, node.id, at, as_of).await?;
        resolved.push(node);
        for mut fact in rows.into_iter().take(limit - facts.len()) {
            let references = utopia_store::graph::fact_evidence(&state.pool, fact.id).await?;
            let ids: Vec<_> = references.iter().map(|r| r.chunk_id).collect();
            let eligible =
                utopia_store::documents::chunks_by_ids(&state.pool, kb, &ids, as_of).await?;
            let eligible: std::collections::HashSet<_> = eligible.iter().map(|r| r.id).collect();
            let references: Vec<_> = references
                .into_iter()
                .filter(|r| eligible.contains(&r.chunk_id))
                .take(8)
                .collect();
            fact.document_ids = references.iter().map(|r| r.document_id).collect();
            fact.evidence_count = references.len() as i64;
            if as_of.is_some() {
                fact.last_evidence_time = None;
            }
            // The ledger selected the fact using both axes. Evidence document
            // versions are returned explicitly; never present current text as old.
            for reference in references {
                evidence.push(json!({"fact_id":fact.id,"source":reference}));
            }
            facts.push(fact);
        }
        if facts.len() >= limit {
            break;
        }
    }
    let conflicts: Vec<_> = facts.iter().filter_map(|f| f.contested.as_ref()).collect();
    Ok(Json(json!({
        "schema_version":"soorin.knowledge-context.v2", "query_id":Uuid::now_v7(),
        "tenant_id":query.tenant_id,"knowledge_base_id":kb,"requested_entity":query.entity,
        "resolved_entities":resolved,"facts":facts,"evidence_references":evidence,
        "valid_time":at,"knowledge_time":as_of,"retrieval_methods":["entity_lookup","temporal_graph","fact_evidence"],
        "retrieval_status":if resolved.is_empty(){"unavailable"}else{"complete"},
        "conflicts":conflicts,"model_versions":{},"latency_ms":started.elapsed().as_millis(),
        "limitations":["bounded to five entity candidates and 100 facts","open facts have inferred=true","no generated claim is approved by this endpoint"]
    })))
}
