//! Runtime profile of the published v1 contract, checked before any writes.
use serde_json::Value;
use std::collections::{HashMap, HashSet};

fn object(value: &Value, allowed: &[&str]) -> anyhow::Result<()> {
    let row = value
        .as_object()
        .ok_or_else(|| anyhow::anyhow!("soc_object_required"))?;
    anyhow::ensure!(
        row.keys().all(|key| allowed.contains(&key.as_str())),
        "soc_unknown_field"
    );
    Ok(())
}
fn text<'a>(value: &'a Value, key: &str) -> anyhow::Result<&'a str> {
    value[key]
        .as_str()
        .filter(|v| !v.trim().is_empty() && v.chars().count() <= 512)
        .ok_or_else(|| anyhow::anyhow!("soc_identifier_invalid"))
}
fn array<'a>(value: &'a Value, key: &str, max: usize) -> anyhow::Result<&'a [Value]> {
    match value.get(key) {
        None => Ok(&[]),
        Some(Value::Array(rows)) if rows.len() <= max => Ok(rows),
        _ => anyhow::bail!("soc_array_invalid"),
    }
}
fn optional_text(value: &Value, keys: &[&str]) -> anyhow::Result<()> {
    for key in keys {
        if let Some(value) = value.get(key) {
            anyhow::ensure!(value.is_string(), "soc_text_invalid");
        }
    }
    Ok(())
}
fn times(value: &Value, keys: &[&str]) -> anyhow::Result<()> {
    for key in keys {
        if let Some(value) = value.get(key) {
            chrono::DateTime::parse_from_rfc3339(
                value
                    .as_str()
                    .ok_or_else(|| anyhow::anyhow!("soc_time_invalid"))?,
            )?;
        }
    }
    if let (Some(start), Some(end)) = (value.get("valid_from"), value.get("valid_to")) {
        anyhow::ensure!(
            chrono::DateTime::parse_from_rfc3339(start.as_str().unwrap())?
                <= chrono::DateTime::parse_from_rfc3339(end.as_str().unwrap())?,
            "soc_reversed_interval"
        );
    }
    Ok(())
}
fn strings(value: &Value, key: &str, max: usize) -> anyhow::Result<()> {
    for item in array(value, key, max)? {
        anyhow::ensure!(
            item.as_str()
                .is_some_and(|s| !s.trim().is_empty() && s.chars().count() <= 512),
            "soc_string_array_invalid"
        );
    }
    Ok(())
}
fn mapping(value: &Value, key: &str) -> anyhow::Result<()> {
    if let Some(value) = value.get(key) {
        anyhow::ensure!(value.is_object(), "soc_mapping_invalid");
    }
    Ok(())
}
pub fn validate(event: &Value) -> anyhow::Result<()> {
    anyhow::ensure!(
        serde_json::to_vec(event)?.len() <= 1024 * 1024,
        "soc_payload_too_large"
    );
    object(
        event,
        &[
            "schema_version",
            "tenant_id",
            "source_system",
            "source_instance",
            "source_record_id",
            "event_id",
            "event_type",
            "event_time",
            "observed_at",
            "recorded_at",
            "processed_at",
            "source_revision_id",
            "delivery_id",
            "curated_payload_version",
            "content_checksum_version",
            "content_checksum",
            "source_references",
            "attributes",
            "vendor_fields",
            "entities",
            "relations",
            "facts",
            "evidence",
        ],
    )?;
    optional_text(event, &["source_revision_id", "delivery_id"])?;
    if let Some(v) = event.get("curated_payload_version") {
        anyhow::ensure!(v.is_string() || v.is_null(), "soc_payload_version_invalid");
    }
    times(
        event,
        &["event_time", "observed_at", "recorded_at", "processed_at"],
    )?;
    strings(event, "source_references", 256)?;
    mapping(event, "attributes")?;
    mapping(event, "vendor_fields")?;
    let spec: Value = serde_json::from_str(include_str!(
        "../../../../soorin/ontology/soc_ontology_v1.yaml"
    ))?;
    let mut entities = HashSet::new();
    let mut entity_kinds = HashMap::new();
    for entity in array(event, "entities", 128)? {
        object(
            entity,
            &[
                "entity_id",
                "entity_type",
                "normalized_value",
                "source_identifiers",
                "aliases",
                "scope",
                "provisional",
                "attributes",
            ],
        )?;
        let id = text(entity, "entity_id")?;
        anyhow::ensure!(
            id.starts_with("soorin:") && entities.insert(id),
            "soc_canonical_id_invalid"
        );
        let kind = text(entity, "entity_type")?;
        anyhow::ensure!(
            spec["entity_types"]
                .as_array()
                .unwrap()
                .iter()
                .any(|row| row["label"]
                    .as_str()
                    .is_some_and(|label| label.replace(' ', "") == kind)),
            "soc_entity_type_unknown"
        );
        let kind_key = spec["entity_types"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| {
                row["label"]
                    .as_str()
                    .is_some_and(|label| label.replace(' ', "") == kind)
            })
            .unwrap()["key"]
            .as_str()
            .unwrap();
        entity_kinds.insert(id, kind_key);
        text(entity, "normalized_value")?;
        let authority = entity["source_identifiers"]
            .as_object()
            .ok_or_else(|| anyhow::anyhow!("soc_authority_object_required"))?;
        anyhow::ensure!(
            authority.len() <= 16
                && authority.iter().all(|(k, v)| !k.trim().is_empty()
                    && k.len() <= 128
                    && v.as_str()
                        .is_some_and(|v| !v.trim().is_empty() && v.chars().count() <= 512)),
            "soc_authority_invalid"
        );
        anyhow::ensure!(
            entity["provisional"].is_boolean()
                && entity["attributes"].is_object()
                && entity["aliases"].is_array(),
            "soc_entity_fields_required"
        );
        strings(entity, "aliases", 128)?;
        if let Some(scope) = entity.get("scope") {
            anyhow::ensure!(
                scope.is_null()
                    || scope
                        .as_str()
                        .is_some_and(|s| !s.trim().is_empty() && s.len() <= 512),
                "soc_scope_invalid"
            );
        }
        // Value-only/provisional observations never enter the authority registry.
        anyhow::ensure!(
            entity["provisional"] != true || authority.is_empty(),
            "soc_provisional_authority_ambiguous"
        );
    }
    anyhow::ensure!(!entities.is_empty(), "soc_entities_required");
    let mut evidence_ids = HashSet::new();
    for evidence in array(event, "evidence", 256)? {
        object(
            evidence,
            &[
                "evidence_id",
                "source_record_id",
                "field_path",
                "source_uri",
                "checksum",
                "excerpt",
                "observed_at",
                "source_system",
                "source_instance",
                "source_event_ids",
                "source_revision_id",
            ],
        )?;
        anyhow::ensure!(
            evidence_ids.insert(text(evidence, "evidence_id")?),
            "soc_evidence_duplicate"
        );
        text(evidence, "source_record_id")?;
        optional_text(
            evidence,
            &[
                "field_path",
                "source_uri",
                "checksum",
                "excerpt",
                "source_system",
                "source_instance",
                "source_revision_id",
            ],
        )?;
        anyhow::ensure!(
            evidence["excerpt"]
                .as_str()
                .is_none_or(|s| s.chars().count() <= 4096),
            "soc_evidence_excerpt_too_large"
        );
        strings(evidence, "source_event_ids", 256)?;
        times(evidence, &["observed_at"])?;
    }
    for (collection, identifier, allowed) in [
        (
            "relations",
            "relation_id",
            &[
                "relation_id",
                "relation_type",
                "subject_entity_id",
                "object_entity_id",
                "confidence_category",
                "evidence_ids",
                "attributes",
                "valid_from",
                "valid_to",
            ][..],
        ),
        (
            "facts",
            "fact_id",
            &[
                "fact_id",
                "subject_entity_id",
                "predicate",
                "object_entity_id",
                "object_value",
                "recorded_at",
                "invalidated_at",
                "valid_from",
                "valid_to",
                "evidence_ids",
                "confidence_category",
            ][..],
        ),
    ] {
        let mut seen = HashSet::new();
        for row in array(event, collection, 512)? {
            object(row, allowed)?;
            anyhow::ensure!(
                seen.insert(text(row, identifier)?),
                "soc_fact_or_relation_duplicate"
            );
            anyhow::ensure!(
                entities.contains(text(row, "subject_entity_id")?),
                "soc_subject_missing"
            );
            if let Some(object) = row.get("object_entity_id") {
                anyhow::ensure!(
                    object.as_str().is_some_and(|v| entities.contains(v)),
                    "soc_object_missing"
                );
            }
            let category = text(row, "confidence_category")?;
            // Inferred/model output requires a distinct review workflow.
            anyhow::ensure!(
                matches!(category, "observed" | "asserted"),
                "soc_unreviewed_conclusion"
            );
            anyhow::ensure!(row["evidence_ids"].is_array(), "soc_evidence_ids_required");
            strings(row, "evidence_ids", 256)?;
            for id in array(row, "evidence_ids", 256)? {
                anyhow::ensure!(
                    evidence_ids.contains(id.as_str().unwrap()),
                    "soc_evidence_missing"
                );
            }
            times(
                row,
                &["valid_from", "valid_to", "recorded_at", "invalidated_at"],
            )?;
            if collection == "relations" {
                let normalize = |value: &str| {
                    value
                        .chars()
                        .filter(|c| c.is_ascii_alphanumeric())
                        .flat_map(char::to_lowercase)
                        .collect::<String>()
                };
                let relation = text(row, "relation_type")?;
                let relation = spec["relation_types"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|r| normalize(r["key"].as_str().unwrap()) == normalize(relation))
                    .ok_or_else(|| anyhow::anyhow!("soc_relation_type_unknown"))?;
                let subject = entity_kinds[text(row, "subject_entity_id")?];
                let object = entity_kinds[text(row, "object_entity_id")?];
                anyhow::ensure!(
                    relation["domains"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|kind| kind.as_str() == Some(subject)),
                    "soc_relation_domain_invalid"
                );
                anyhow::ensure!(
                    relation["ranges"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|kind| kind.as_str() == Some(object)),
                    "soc_relation_range_invalid"
                );
                anyhow::ensure!(
                    relation["required_provenance"] != true
                        || !row["evidence_ids"].as_array().unwrap().is_empty(),
                    "soc_relation_evidence_required"
                );
                anyhow::ensure!(
                    row["attributes"].is_object(),
                    "soc_relation_attributes_required"
                );
            } else {
                text(row, "predicate")?;
                text(row, "recorded_at")?;
                anyhow::ensure!(
                    row.get("object_entity_id").is_some() != row.get("object_value").is_some(),
                    "soc_fact_object_ambiguous"
                );
                anyhow::ensure!(
                    row.get("object_value").is_none_or(|v| !v.is_null()),
                    "soc_fact_value_missing"
                );
                anyhow::ensure!(
                    row.get("invalidated_at").is_none(),
                    "soc_retraction_requires_review"
                );
            }
        }
    }
    Ok(())
}

/// Receipt storage accepts curated events by default. Explicit deployment policy
/// may retain sensitive source payloads; that is never enabled by a request.
pub fn storage_policy(event: &Value, allow_sensitive: bool) -> anyhow::Result<()> {
    if allow_sensitive {
        return Ok(());
    }
    fn safe(value: &Value) -> bool {
        match value {
            Value::Object(row) => row.iter().all(|(key, value)| {
                !matches!(
                    key.to_lowercase().as_str(),
                    "_raw"
                        | "raw"
                        | "raw_record"
                        | "raw_payload"
                        | "message"
                        | "log"
                        | "logs"
                        | "password"
                        | "passwd"
                        | "secret"
                        | "token"
                        | "access_token"
                        | "api_key"
                        | "authorization"
                        | "cookie"
                        | "credentials"
                        | "prompt"
                        | "response"
                ) && safe(value)
            }),
            Value::Array(rows) => rows.iter().all(safe),
            _ => true,
        }
    }
    anyhow::ensure!(
        event["vendor_fields"]
            .as_object()
            .is_none_or(|m| m.is_empty()),
        "soc_sensitive_payload_policy"
    );
    anyhow::ensure!(
        safe(&event["attributes"])
            && safe(&event["entities"])
            && safe(&event["relations"])
            && safe(&event["facts"]),
        "soc_sensitive_payload_policy"
    );
    anyhow::ensure!(
        event["evidence"].as_array().is_none_or(|rows| rows
            .iter()
            .all(|e| e["excerpt"].as_str().is_none_or(str::is_empty))),
        "soc_excerpt_requires_storage_policy"
    );
    Ok(())
}

#[cfg(test)]
mod storage_tests {
    use super::*;
    #[test]
    fn raw_payloads_and_excerpts_require_deployment_policy() {
        for event in [
            serde_json::json!({"vendor_fields":{"x":"value"}}),
            serde_json::json!({"attributes":{"nested":{"password":"private"}}}),
            serde_json::json!({"evidence":[{"excerpt":"private"}]}),
        ] {
            assert!(storage_policy(&event, false).is_err());
            assert!(storage_policy(&event, true).is_ok());
        }
        assert!(storage_policy(
            &serde_json::json!({"attributes":{"source_record_id":"synthetic"}}),
            false
        )
        .is_ok());
    }
}

#[cfg(test)]
mod relation_tests {
    use super::*;
    use serde_json::json;
    fn event() -> Value {
        let mut event: Value = serde_json::from_str::<Value>(include_str!(
            "../../../../soorin/tests/fixtures/soc_canonical_minimal_v1.json"
        ))
        .unwrap()["event"]
            .clone();
        event["entities"] = json!([
            {"entity_id":"soorin:a","entity_type":"SecurityAlert","normalized_value":"A","source_identifiers":{},"aliases":[],"attributes":{},"provisional":false},
            {"entity_id":"soorin:b","entity_type":"Host","normalized_value":"H","source_identifiers":{},"aliases":[],"attributes":{},"provisional":false}]);
        event["evidence"] = json!([{"evidence_id":"e","source_record_id":"A"}]);
        event["relations"] = json!([{"relation_id":"r","relation_type":"observed_on","subject_entity_id":"soorin:a","object_entity_id":"soorin:b","evidence_ids":["e"],"confidence_category":"asserted","attributes":{}}]);
        event
    }
    #[test]
    fn reviewed_relations_require_valid_endpoints_and_evidence() {
        for spelling in ["observed_on", "observed on", "observedOn"] {
            let mut value = event();
            value["relations"][0]["relation_type"] = json!(spelling);
            validate(&value).unwrap();
            assert_eq!(value["relations"][0]["confidence_category"], "asserted");
        }
        for (collection, index, field, bad) in [
            ("relations", 0, "relation_type", json!("unknown_relation")),
            ("entities", 0, "entity_type", json!("Ticket")),
            ("entities", 1, "entity_type", json!("UserAccount")),
            ("relations", 0, "object_entity_id", json!("soorin:missing")),
            ("relations", 0, "evidence_ids", json!([])),
            ("relations", 0, "evidence_ids", json!(["missing"])),
            (
                "relations",
                0,
                "confidence_category",
                json!("model_proposed"),
            ),
        ] {
            let mut value = event();
            value[collection][index][field] = bad;
            assert!(validate(&value).is_err(), "{collection}.{field}");
        }
    }
}
