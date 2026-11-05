//! Optional CPU reranking after authorized/temporal chunk reload and before top-k.
use serde::{Deserialize, Serialize};
use utopia_core::models::ChunkView;
use uuid::Uuid;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub enabled: bool,
    pub base_url: String,
    pub model: String,
    pub fallback: bool,
}

pub async fn config(pool: &sqlx::PgPool, workspace: Uuid) -> anyhow::Result<Config> {
    let value: Option<(serde_json::Value,)> =
        sqlx::query_as("SELECT reranker FROM soorin_workspace_runtime WHERE workspace_id=$1")
            .bind(workspace)
            .fetch_optional(pool)
            .await?;
    Ok(value
        .map(|(value,)| serde_json::from_value(value))
        .transpose()?
        .unwrap_or_default())
}

pub fn ordered(rows: &serde_json::Value, size: usize) -> anyhow::Result<Vec<usize>> {
    let rows = rows
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("rerank_invalid_shape"))?;
    anyhow::ensure!(rows.len() == size, "rerank_missing_scores");
    let mut seen = std::collections::HashSet::new();
    let mut scores = Vec::new();
    for row in rows {
        let index = row["index"]
            .as_u64()
            .ok_or_else(|| anyhow::anyhow!("rerank_invalid_index"))? as usize;
        let score = row["score"]
            .as_f64()
            .filter(|v| v.is_finite())
            .ok_or_else(|| anyhow::anyhow!("rerank_invalid_score"))?;
        anyhow::ensure!(index < size && seen.insert(index), "rerank_invalid_index");
        scores.push((index, score));
    }
    scores.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    Ok(scores.into_iter().map(|(index, _)| index).collect())
}

pub async fn apply(
    pool: &sqlx::PgPool,
    workspace: Uuid,
    query: &str,
    chunks: &mut Vec<ChunkView>,
) -> anyhow::Result<&'static str> {
    let cfg = config(pool, workspace).await?;
    if !cfg.enabled || chunks.is_empty() {
        return Ok("disabled");
    }
    chunks.truncate(16);
    let result = async {
        utopia_llm::egress::require(&cfg.base_url)?;
        let texts: Vec<String> = chunks.iter().map(|row| row.text.chars().take(8000).collect()).collect();
        let http = reqwest::Client::builder().timeout(std::time::Duration::from_secs(30))
            .redirect(reqwest::redirect::Policy::none()).build()?;
        let response = http.post(format!("{}/rerank",cfg.base_url.trim_end_matches('/')))
            .json(&serde_json::json!({"query":query.chars().take(4000).collect::<String>(),"texts":texts,"model":cfg.model})).send().await?;
        anyhow::ensure!(response.status().is_success(), "rerank_provider_rejected");
        let rows: serde_json::Value = response.json().await?;
        ordered(&rows, chunks.len())
    }.await;
    match result {
        Ok(order) => {
            let original = chunks.clone();
            *chunks = order
                .into_iter()
                .map(|index| original[index].clone())
                .collect();
            Ok("complete")
        }
        Err(_) if cfg.fallback => {
            tracing::warn!(%workspace, "reranker unavailable; preserving RRF ranking");
            Ok("fallback")
        }
        Err(_) => anyhow::bail!("reranker_unavailable_and_fallback_disabled"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_scores_are_checked_before_ranking() {
        assert_eq!(
            ordered(
                &serde_json::json!([{"index":0,"score":0.2},{"index":1,"score":0.9}]),
                2
            )
            .unwrap(),
            vec![1, 0]
        );
        assert!(ordered(
            &serde_json::json!([{"index":0,"score":0.2},{"index":0,"score":0.9}]),
            2
        )
        .is_err());
        assert!(ordered(&serde_json::json!([{"index":0,"score":0.2}]), 2).is_err());
    }
}
