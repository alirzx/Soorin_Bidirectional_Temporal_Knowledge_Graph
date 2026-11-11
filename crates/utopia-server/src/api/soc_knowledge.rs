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

/// Exact current authority lookup. No alias, fuzzy or similarity fallback.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResolveQuery {
    tenant_id: String,
    source_system: String,
    source_instance: String,
    entity_type: String,
    authority_name: String,
    source_identifier: String,
    scope: Option<String>,
}

impl ResolveQuery {
    fn authority_key(&self) -> Result<String, utopia_core::AppError> {
        for (value, max) in [
            (&self.tenant_id, 512),
            (&self.source_system, 512),
            (&self.source_instance, 512),
            (&self.entity_type, 128),
            (&self.authority_name, 128),
            (&self.source_identifier, 512),
        ] {
            if value.trim().is_empty() || value.len() > max {
                return Err(utopia_core::AppError::Validation(
                    "invalid identity query".into(),
                ));
            }
        }
        if self
            .scope
            .as_ref()
            .is_some_and(|s| s.trim().is_empty() || s.len() > 512)
        {
            return Err(utopia_core::AppError::Validation(
                "invalid identity scope".into(),
            ));
        }
        Ok(format!(
            "authority-v1:{}",
            json!([self.authority_name, self.source_identifier, self.scope])
        ))
    }
}

pub async fn resolve(
    State(state): State<AppState>,
    reader: DocumentReader,
    Path(kb): Path<Uuid>,
    Json(query): Json<ResolveQuery>,
) -> ApiResult<Json<serde_json::Value>> {
    super::documents_routes::require_reader_kb(&state, &reader, kb).await?;
    let key = query.authority_key()?;
    let binding: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM soorin_kb_tenants WHERE kb_id=$1 AND tenant_id=$2
         AND source_system=$3 AND source_instance=$4)",
    )
    .bind(kb)
    .bind(&query.tenant_id)
    .bind(&query.source_system)
    .bind(&query.source_instance)
    .fetch_one(&state.pool)
    .await?;
    if !binding {
        return Err(utopia_core::AppError::NotFound.into());
    }
    let row: Option<(Uuid, String, Option<Uuid>, String, bool)> = sqlx::query_as(
        "SELECT i.id,i.canonical_key,e.id,i.status,
          EXISTS(SELECT 1 FROM soorin_identity_conflicts c WHERE c.authority_id=a.id AND c.resolved_at IS NULL)
         FROM soorin_identity_authorities a
         JOIN soorin_canonical_identities i ON i.id=a.identity_id AND i.kb_id=a.kb_id AND i.tenant_id=a.tenant_id
         LEFT JOIN entities e ON e.id=i.utopia_entity_id AND e.kb_id=i.kb_id AND e.merged_into IS NULL
         WHERE a.kb_id=$1 AND a.tenant_id=$2 AND a.source_system=$3 AND a.source_instance=$4
           AND a.entity_type=$5 AND a.source_identifier=$6",
    ).bind(kb).bind(&query.tenant_id).bind(&query.source_system).bind(&query.source_instance)
        .bind(&query.entity_type).bind(key).fetch_optional(&state.pool).await?;
    let (status, candidates) = match row {
        None => ("not_found", vec![]),
        Some((id, key, entity, state, conflict)) => {
            let status = if conflict || state == "ambiguous" {
                "ambiguous"
            } else if state != "active" {
                "unavailable"
            } else if entity.is_none() {
                "pending_materialization"
            } else {
                "resolved"
            };
            (
                status,
                vec![
                    json!({"identity_id":id,"canonical_key":key,"entity_id":entity,
                "identity_status":state,"has_conflict":conflict}),
                ],
            )
        }
    };
    Ok(Json(
        json!({"schema_version":"soorin.identity-resolution.v1", "knowledge_base_id":kb,
        "tenant_id":query.tenant_id,"status":status,"automatic":status=="resolved","candidates":candidates,
        "limitations":["current authority mapping only; use returned UUID with context at/as_of",
        "provisional names without source authority are not exact matches",
        "not_found does not establish absence of a threat"]}),
    ))
}

#[cfg(test)]
mod resolve_tests {
    use super::*;

    #[test]
    fn authority_tuple_retains_scope_and_rejects_empty_values() {
        let mut q: ResolveQuery =
            serde_json::from_value(json!({"tenant_id":"blue","source_system":"splunk",
            "source_instance":"one","entity_type":"IPAddress","authority_name":"ip_id",
            "source_identifier":"10.0.0.1","scope":"a"}))
            .unwrap();
        let a = q.authority_key().unwrap();
        q.scope = Some("b".into());
        assert_ne!(a, q.authority_key().unwrap());
        q.source_identifier.clear();
        assert!(q.authority_key().is_err());
    }
}
