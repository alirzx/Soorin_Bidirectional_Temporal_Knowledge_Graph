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
    if as_of.is_some() && (query.entity.parse::<Uuid>().is_err() || query.entity_type.is_some()) {
        return Err(utopia_core::AppError::Validation(
            "historical context requires an entity UUID and no current-type filter".into(),
        )
        .into());
    }
    let limit = query.limit.unwrap_or(40).clamp(1, 100);
    let (nodes, lookup_more) = if let Ok(id) = query.entity.parse::<Uuid>() {
        (
            utopia_store::graph::entity_node_visible(&state.pool, kb, id, as_of)
                .await?
                .into_iter()
                .collect(),
            false,
        )
    } else {
        let (rows, total) =
            utopia_store::graph::search_entities(&state.pool, kb, &query.entity, 20, 0, as_of)
                .await?;
        let more = total > rows.len() as i64;
        (rows, more)
    };
    let nodes: Vec<_> = nodes
        .into_iter()
        .filter(|n| {
            query
                .entity_type
                .as_deref()
                .is_none_or(|kind| n.type_key.as_deref() == Some(kind))
        })
        .collect();
    let candidate_count = nodes.len();
    let mut truncated = lookup_more || candidate_count > 5;
    let mut facts = Vec::new();
    let mut evidence = Vec::new();
    let mut resolved = Vec::new();
    for (node_index, node) in nodes.into_iter().take(5).enumerate() {
        let (mut node, rows) = utopia_store::graph::entity_detail_bounded(
            &state.pool,
            kb,
            node.id,
            at,
            as_of,
            Some((limit + 1) as i64),
        )
        .await?;
        if as_of.is_some() {
            node.name = node.id.to_string();
            node.type_key = None;
            node.type_label = None;
            node.disambiguator = None;
        }
        resolved.push(node);
        truncated |= rows.len() > limit - facts.len();
        for mut fact in rows.into_iter().take(limit - facts.len()) {
            let references =
                utopia_store::graph::fact_evidence_bounded(&state.pool, fact.id, as_of, Some(65))
                    .await?;
            truncated |= references.len() > 64;
            let references: Vec<_> = references.into_iter().take(64).collect();
            let ids: Vec<_> = references.iter().map(|r| r.chunk_id).collect();
            let eligible =
                utopia_store::documents::chunks_by_ids(&state.pool, kb, &ids, as_of).await?;
            let eligible: std::collections::HashSet<_> = eligible.iter().map(|r| r.id).collect();
            let mut references: Vec<_> = references
                .into_iter()
                .filter(|r| eligible.contains(&r.chunk_id))
                .collect();
            truncated |= references.len() > 8;
            references.truncate(8);
            fact.document_ids = references.iter().map(|r| r.document_id).collect();
            fact.evidence_count = references.len() as i64;
            if as_of.is_some() {
                fact.last_evidence_time = None;
                fact.predicate_label = None;
                fact.invalidated_at = fact.invalidated_at.filter(|time| Some(*time) <= as_of);
                fact.closed_by_id = None;
                fact.closed_by_value = None;
                fact.other_name = fact.other_id.map(|id| id.to_string());
                fact.other_type = None;
                fact.closed_by = None;
                fact.correction_note = None;
                fact.attested_by = None;
                for qualifier in &mut fact.qualifiers {
                    qualifier.entity_name = qualifier.entity_id.map(|id| id.to_string());
                }
            }
            // The ledger selected the fact using both axes. Evidence document
            // versions are returned explicitly; never present current text as old.
            for mut reference in references {
                if as_of.is_some() {
                    reference.stale = false;
                    reference.document_deleted = false;
                    reference.filename =
                        format!("{}-v{}", reference.document_id, reference.doc_version);
                }
                evidence.push(json!({"fact_id":fact.id,"source":reference}));
            }
            facts.push(fact);
        }
        if facts.len() >= limit {
            truncated |= node_index + 1 < candidate_count;
            break;
        }
    }
    let conflicts: Vec<_> = facts.iter().filter_map(|f| f.contested.as_ref()).collect();
    let partial = truncated || facts.iter().any(|f| f.evidence_count == 0) || !conflicts.is_empty();
    Ok(Json(json!({
        "schema_version":"soorin.knowledge-context.v2", "query_id":Uuid::now_v7(),
        "tenant_id":query.tenant_id,"knowledge_base_id":kb,"requested_entity":query.entity,
        "resolved_entities":resolved,"facts":facts,"evidence_references":evidence,
        "valid_time":at,"knowledge_time":as_of,"retrieval_methods":["entity_lookup","temporal_graph","fact_evidence"],
        "retrieval_status":if resolved.is_empty(){"unavailable"}else if partial{"partial"}else{"complete"},
        "conflicts":conflicts,"model_versions":{"usage":"none","reason":"deterministic_graph_lookup"},
        "bounds":{"truncated":truncated,"has_more":truncated,"returned_count":facts.len(),"candidate_count":candidate_count,"candidate_count_is_lower_bound":lookup_more,"limit":limit,"entity_limit":5,"evidence_limit_per_fact":8},"latency_ms":started.elapsed().as_millis(),
        "limitations":["bounded to five entity candidates and 100 facts","open facts have inferred=true; this describes alignment, not security confidence","historical evidence excludes legacy links with unknown attachment time","no generated claim is approved by this endpoint"]
    })))
}
