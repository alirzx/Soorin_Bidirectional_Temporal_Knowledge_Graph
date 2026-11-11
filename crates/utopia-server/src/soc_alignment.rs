//! Exact reviewed SOC vocabulary, projected through existing Utopia bindings.
//! Unknown words remain open. Human decisions are preserved by the store API.
use serde_json::Value;
use sqlx::PgPool;
use utopia_core::models::EntityType;
use uuid::Uuid;

fn vocabulary() -> Value {
    serde_json::from_str(include_str!(
        "../../../soorin/ontology/soc_ontology_v1.yaml"
    ))
    .expect("reviewed SOC ontology must be valid JSON")
}

fn token(value: &str) -> String {
    value
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn installed(classes: &[EntityType], spec: &Value) -> bool {
    spec["entity_types"].as_array().unwrap().iter().all(|row| {
        classes.iter().any(|class| {
            class.key == row["key"].as_str().unwrap()
                && class.label == row["label"].as_str().unwrap()
        })
    })
}

pub async fn types(pool: &PgPool, kb_id: Uuid) -> anyhow::Result<bool> {
    let classes = utopia_store::graph::entity_types(pool, kb_id).await?;
    let spec = vocabulary();
    if !installed(&classes, &spec) {
        return Ok(false);
    }
    let snapshot = utopia_store::type_bindings::class_snapshot(pool, kb_id).await?;
    let all_ids: Vec<_> = classes.iter().map(|class| class.id).collect();
    let basis = snapshot.basis(&all_ids);
    let bindings = utopia_store::type_bindings::bindings(pool, kb_id).await?;
    for sig in utopia_store::type_bindings::signatures(pool, kb_id).await? {
        let targets: Vec<_> = spec["entity_types"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|row| {
                token(&sig.kind_word) == token(row["key"].as_str().unwrap())
                    || token(&sig.kind_word) == token(row["label"].as_str().unwrap())
            })
            .filter_map(|row| {
                classes
                    .iter()
                    .find(|class| class.key == row["key"].as_str().unwrap())
            })
            .collect();
        if targets.len() != 1 {
            continue;
        }
        if bindings.iter().any(|b| {
            b.kind_word == sig.kind_word && b.status == "bound" && b.type_id == Some(targets[0].id)
        }) {
            continue;
        }
        utopia_store::type_bindings::decide_and_apply_if_current(
            pool,
            kb_id,
            &sig.kind_word,
            &sig.words,
            Some(targets[0].id),
            "bound",
            &serde_json::json!({"method":"soc_exact_v1"}),
            &basis,
            &all_ids,
        )
        .await?;
    }
    Ok(true)
}

pub async fn phrases(pool: &PgPool, kb_id: Uuid) -> anyhow::Result<bool> {
    let classes = utopia_store::graph::entity_types(pool, kb_id).await?;
    let spec = vocabulary();
    if !installed(&classes, &spec) {
        return Ok(false);
    }
    let props = utopia_store::ontology::relation_type_views(pool, kb_id).await?;
    let bindings = utopia_store::phrase_bindings::bindings(pool, kb_id).await?;
    for sig in utopia_store::phrase_bindings::signatures(pool, kb_id).await? {
        let Some(subject) = sig.subject_type_key.as_deref() else {
            continue;
        };
        let Some(object) = sig.object_type_key.as_deref() else {
            continue;
        };
        if sig.object_is_value {
            continue;
        }
        let matches: Vec<_> = spec["relation_types"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|row| {
                (token(&sig.phrase) == token(row["key"].as_str().unwrap())
                    || token(&sig.phrase) == token(row["label"].as_str().unwrap()))
                    && row["domains"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|v| v.as_str() == Some(subject))
                    && row["ranges"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|v| v.as_str() == Some(object))
            })
            .collect();
        if matches.len() != 1 {
            continue;
        }
        let row = matches[0];
        let Some(prop) = props.iter().find(|p| {
            p.key == row["key"].as_str().unwrap()
                && (p.label == row["label"].as_str().unwrap()
                    || p.label
                        == utopia_store::ontology::lower_camel(row["label"].as_str().unwrap()))
                && p.temporal == row["temporal"].as_str().unwrap()
                && p.domains.contains(&sig.subject_type_id.unwrap())
                && p.ranges.contains(&sig.object_type_id.unwrap())
        }) else {
            continue;
        };
        if bindings.iter().any(|b| {
            b.key() == sig.key() && b.status == "bound" && b.relation_type_id == Some(prop.id)
        }) {
            continue;
        }
        utopia_store::phrase_bindings::decide_with_delivery(
            pool,
            kb_id,
            &sig,
            utopia_store::phrase_bindings::Decision {
                relation_type_id: Some(prop.id),
                direction: Some("forward"),
                status: "bound",
                votes: &serde_json::json!({"method":"soc_exact_v1"}),
                decided_by: "agent",
                basis: None,
                marks: Some("start"),
                marks_asked: true,
            },
        )
        .await?;
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn exact_soc_vocabulary_materializes_without_chat_and_keeps_unknown_open(
    ) -> anyhow::Result<()> {
        let Some(url) = utopia_store::test_db::url() else {
            return Ok(());
        };
        let pool = sqlx::PgPool::connect(&url).await?;
        let (org, ws, kb, alert, host, unknown, relation, chunk) = (
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
        );
        sqlx::raw_sql(&format!("INSERT INTO organizations(id,name) VALUES('{org}','soc-alignment-test');
          INSERT INTO workspaces(id,org_id,name) VALUES('{ws}','{org}','soc-alignment-test');
          INSERT INTO knowledge_bases(id,workspace_id,name) VALUES('{kb}','{ws}','soc-alignment-test');" )).execute(&pool).await?;
        for row in vocabulary()["entity_types"].as_array().unwrap() {
            sqlx::query(
                "INSERT INTO entity_types(id,kb_id,key,label,description) VALUES($1,$2,$3,$4,$5)",
            )
            .bind(Uuid::now_v7())
            .bind(kb)
            .bind(row["key"].as_str())
            .bind(row["label"].as_str())
            .bind(row["description"].as_str())
            .execute(&pool)
            .await?;
        }
        for (id, name, kind) in [
            (alert, "A1", "SecurityAlert"),
            (host, "host.synthetic.example", "Host"),
            (unknown, "unclassified", "System"),
        ] {
            sqlx::query(
                "INSERT INTO entities(id,kb_id,canonical_name,specific_type) VALUES($1,$2,$3,$4)",
            )
            .bind(id)
            .bind(kb)
            .bind(name)
            .bind(kind)
            .execute(&pool)
            .await?;
        }
        assert!(types(&pool, kb).await?);
        let (host_type,): (Uuid,) = sqlx::query_as("SELECT type_id FROM entities WHERE id=$1")
            .bind(host)
            .fetch_one(&pool)
            .await?;
        let (alert_type,): (Uuid,) = sqlx::query_as("SELECT type_id FROM entities WHERE id=$1")
            .bind(alert)
            .fetch_one(&pool)
            .await?;
        let unknown_type: Option<Uuid> =
            sqlx::query_scalar("SELECT type_id FROM entities WHERE id=$1")
                .bind(unknown)
                .fetch_one(&pool)
                .await?;
        assert!(unknown_type.is_none());
        sqlx::query("INSERT INTO relation_types(id,kb_id,key,label,temporal) VALUES($1,$2,'observed_on','observedOn','event')").bind(relation).bind(kb).execute(&pool).await?;
        sqlx::query(
            "INSERT INTO relation_type_domains(relation_type_id,entity_type_id) VALUES($1,$2)",
        )
        .bind(relation)
        .bind(alert_type)
        .execute(&pool)
        .await?;
        sqlx::query(
            "INSERT INTO relation_type_ranges(relation_type_id,entity_type_id) VALUES($1,$2)",
        )
        .bind(relation)
        .bind(host_type)
        .execute(&pool)
        .await?;
        let doc = utopia_store::documents::create(
            &pool,
            kb,
            "synthetic.txt",
            "text/plain",
            1,
            &Uuid::now_v7().to_string(),
            None,
            None,
            None,
        )
        .await?;
        sqlx::query("INSERT INTO chunks(id,kb_id,document_id,seq,text) VALUES($1,$2,$3,0,'A1 observed on host')").bind(chunk).bind(kb).bind(doc.id).execute(&pool).await?;
        let (fact, _) = utopia_store::graph::insert_open_statement(
            &pool,
            kb,
            alert,
            "observed on",
            utopia_store::graph::FactObject::Entity(host),
            None,
            1.0,
        )
        .await?;
        utopia_store::graph::add_evidence(
            &pool,
            fact,
            chunk,
            Some("A1 observed on host"),
            Some("observed on"),
        )
        .await?;
        assert!(phrases(&pool, kb).await?);
        utopia_store::materialize::materialize(&pool, kb).await?;
        let count:i64=sqlx::query_scalar("SELECT count(*) FROM facts WHERE kb_id=$1 AND predicate_id=$2 AND layer='typed' AND invalidated_at IS NULL").bind(kb).bind(relation).fetch_one(&pool).await?;
        assert_eq!(count, 1);
        sqlx::query("DELETE FROM jobs WHERE payload->>'kb_id'=$1")
            .bind(kb.to_string())
            .execute(&pool)
            .await?;
        sqlx::query("DELETE FROM organizations WHERE id=$1")
            .bind(org)
            .execute(&pool)
            .await?;
        Ok(())
    }
    #[test]
    fn reviewed_kind_words_are_exact_and_distinct() {
        assert_eq!(token("SecurityAlert"), token("security_alert"));
        assert_eq!(token("IP Address"), token("ip_address"));
        assert_ne!(token("SecurityEvent"), token("SecurityAlert"));
        assert_ne!(token("system"), token("host"));
        assert_eq!(vocabulary()["entity_types"].as_array().unwrap().len(), 17);
    }
}
