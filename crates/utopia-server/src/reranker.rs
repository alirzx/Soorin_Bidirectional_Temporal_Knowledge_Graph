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


/// CPU-first reranking limits are deployment-owned, not workspace-provided.
/// Values outside the documented range fall back to safe defaults.
fn bounded(value: Option<&str>, default: usize, min: usize, max: usize) -> usize {
    value
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|n| (min..=max).contains(n))
        .unwrap_or(default)
}

fn tuning() -> (usize, u64) {
    let batch = std::env::var("SOORIN_RERANK_BATCH_SIZE").ok();
    let timeout = std::env::var("SOORIN_RERANK_TIMEOUT_SECONDS").ok();
    (
        bounded(batch.as_deref(), 8, 1, 16),
        bounded(timeout.as_deref(), 90, 5, 180) as u64,
    )
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
    let (batch_size, timeout_seconds) = tuning();
    let started = std::time::Instant::now();
    let result: anyhow::Result<Vec<usize>> = async {
        utopia_llm::egress::require(&cfg.base_url)
            .map_err(|_| anyhow::anyhow!("egress_blocked"))?;
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(timeout_seconds))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| anyhow::anyhow!("client_configuration"))?;
        // Recall is bounded to 48. Never omit the tail or silently mix
        // reranked and unreranked candidates; one failed batch falls back
        // to the complete pre-rerank RRF order.
        anyhow::ensure!(chunks.len() <= 48, "candidate_bound");
        let mut scores = Vec::with_capacity(chunks.len());
        for (batch, rows) in chunks.chunks(batch_size).enumerate() {
            let texts: Vec<String> = rows
                .iter()
                .map(|row| row.text.chars().take(8000).collect())
                .collect();
            let response = http
                .post(format!("{}/rerank", cfg.base_url.trim_end_matches('/')))
                .json(&serde_json::json!({
                    "query": query.chars().take(4000).collect::<String>(),
                    "texts": texts,
                    "model": cfg.model
                }))
                .send()
                .await
                .map_err(|error| {
                    if error.is_timeout() {
                        anyhow::anyhow!("provider_timeout")
                    } else if error.is_connect() {
                        anyhow::anyhow!("provider_connect")
                    } else {
                        anyhow::anyhow!("provider_transport")
                    }
                })?;
            anyhow::ensure!(
                response.status().is_success(),
                "provider_http_{}",
                response.status().as_u16()
            );
            let response: serde_json::Value = response
                .json()
                .await
                .map_err(|_| anyhow::anyhow!("provider_invalid_json"))?;
            ordered(&response, rows.len())
                .map_err(|_| anyhow::anyhow!("provider_invalid_scores"))?;
            // Index is batch-local in the model response.
            for row in response.as_array().expect("validated by ordered") {
                let local = row["index"].as_u64().expect("validated by ordered") as usize;
                scores.push(serde_json::json!({
                    "index": batch * batch_size + local,
                    "score": row["score"]
                }));
            }
        }
        ordered(&serde_json::Value::Array(scores), chunks.len())
            .map_err(|_| anyhow::anyhow!("aggregate_invalid_scores"))
    }
    .await;
    match result {
        Ok(order) => {
            let original = chunks.clone();
            *chunks = order
                .into_iter()
                .map(|index| original[index].clone())
                .collect();
            tracing::debug!(
                %workspace,
                candidate_count = chunks.len(),
                batch_size,
                elapsed_ms = started.elapsed().as_millis(),
                "reranking complete"
            );
            Ok("complete")
        }
        Err(error) => {
            // Log only controlled status/category, never request text, model
            // payload, provider response bodies, URL or credentials.
            tracing::warn!(
                %workspace,
                reason = %error,
                candidate_count = chunks.len(),
                batch_size,
                timeout_seconds,
                elapsed_ms = started.elapsed().as_millis(),
                "reranker failed"
            );
            if cfg.fallback {
                Ok("fallback")
            } else {
                anyhow::bail!("reranker_unavailable_and_fallback_disabled")
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cpu_first_tuning_is_bounded() {
        assert_eq!(bounded(None, 8, 1, 16), 8);
        assert_eq!(bounded(Some("4"), 8, 1, 16), 4);
        assert_eq!(bounded(Some("0"), 8, 1, 16), 8);
        assert_eq!(bounded(Some("17"), 8, 1, 16), 8);
        assert_eq!(bounded(Some("garbage"), 90, 5, 180), 90);
        assert_eq!(bounded(Some("120"), 90, 5, 180), 120);
    }

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
