//! Optional CPU reranking after authorized/temporal chunk reload and before top-k.
use std::time::Duration;

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

// One foreground reranker per app, leaving provider queue slots for embedding.
static SEARCH_SLOT: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
const MAX_BODY: usize = 300_000;
const MAX_RESPONSE: usize = 16_384;

#[derive(Deserialize)]
struct Score {
    index: usize,
    score: f64,
}

async fn rank(
    client: &reqwest::Client,
    cfg: &Config,
    query: &str,
    texts: &[String],
    batch_size: usize,
) -> anyhow::Result<Vec<usize>> {
    anyhow::ensure!(texts.len() <= 48, "candidate_bound");
    let url = format!("{}/rerank", cfg.base_url.trim_end_matches('/'));
    let mut scores = Vec::with_capacity(texts.len());
    let mut start = 0;
    let mut retry_available = true;
    while start < texts.len() {
        let mut end = texts.len().min(start + batch_size);
        let body = loop {
            let bytes = serde_json::to_vec(&serde_json::json!({
                "model": cfg.model, "query": query, "texts": &texts[start..end],
            }))?;
            if bytes.len() <= MAX_BODY {
                break bytes;
            }
            anyhow::ensure!(end > start + 1, "provider_request_size");
            end = start + (end - start) / 2;
        };
        let mut response = loop {
            let reply = client
                .post(&url)
                .header("Content-Type", "application/json")
                .body(body.clone())
                .send()
                .await
                .map_err(|e| {
                    if e.is_timeout() {
                        anyhow::anyhow!("provider_timeout")
                    } else if e.is_connect() {
                        anyhow::anyhow!("provider_connect")
                    } else {
                        anyhow::anyhow!("provider_transport")
                    }
                })?;
            let status = reply.status().as_u16();
            if retry_available && matches!(status, 429 | 503) {
                let delay = match reply.headers().get("retry-after") {
                    None => Some(Duration::from_millis(250)),
                    Some(header) => header
                        .to_str()
                        .ok()
                        .and_then(|s| s.parse::<u64>().ok())
                        .filter(|s| *s <= 5)
                        .map(Duration::from_secs),
                };
                if let Some(delay) = delay {
                    retry_available = false;
                    drop(reply);
                    tokio::time::sleep(delay).await;
                    continue;
                }
            }
            anyhow::ensure!(reply.status().is_success(), "provider_http_{status}");
            break reply;
        };
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| anyhow::anyhow!("provider_read"))?
        {
            anyhow::ensure!(
                bytes.len() + chunk.len() <= MAX_RESPONSE,
                "provider_response_size"
            );
            bytes.extend_from_slice(&chunk);
        }
        let rows: Vec<Score> = serde_json::from_slice(&bytes).map_err(|error| {
            if error.is_data() {
                anyhow::anyhow!("provider_invalid_scores")
            } else {
                anyhow::anyhow!("provider_invalid_json")
            }
        })?;
        let size = end - start;
        anyhow::ensure!(rows.len() == size, "provider_missing_scores");
        let mut seen = vec![false; size];
        for row in rows {
            anyhow::ensure!(
                row.index < size && !seen[row.index] && row.score.is_finite(),
                "provider_invalid_scores"
            );
            seen[row.index] = true;
            scores.push((start + row.index, row.score));
        }
        start = end;
    }
    scores.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then(a.0.cmp(&b.0)));
    Ok(scores.into_iter().map(|(i, _)| i).collect())
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
    apply_config(&cfg, workspace, query, chunks, &SEARCH_SLOT).await
}

async fn apply_config(
    cfg: &Config,
    workspace: Uuid,
    query: &str,
    chunks: &mut Vec<ChunkView>,
    slot: &tokio::sync::Semaphore,
) -> anyhow::Result<&'static str> {
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
        let _permit = slot
            .try_acquire()
            .map_err(|_| anyhow::anyhow!("search_capacity"))?;
        anyhow::ensure!(chunks.len() <= 48, "candidate_bound");
        let texts: Vec<String> = chunks
            .iter()
            .map(|c| c.text.trim().chars().take(8000).collect())
            .collect();
        let query: String = query.trim().chars().take(4000).collect();
        let deadline = std::env::var("SOORIN_RERANK_DEADLINE_SECONDS").ok();
        let seconds = bounded(deadline.as_deref(), 90, 5, 180);
        tokio::time::timeout(
            Duration::from_secs(seconds as u64),
            rank(&http, cfg, &query, &texts, batch_size),
        )
        .await
        .map_err(|_| anyhow::anyhow!("rerank_deadline"))?
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

    #[tokio::test]
    async fn local_scores_merge_across_wire_batches() {
        use wiremock::{matchers::path, Mock, MockServer, Request, ResponseTemplate};
        let server = MockServer::start().await;
        Mock::given(path("/rerank")).respond_with(|req: &Request| {
            assert!(req.body.len() <= MAX_BODY);
            let body: serde_json::Value = req.body_json().unwrap();
            let rows: Vec<_> = body["texts"].as_array().unwrap().iter().enumerate()
                .map(|(index, text)| serde_json::json!({"index":index, "score":text.as_str().unwrap().split(':').next().unwrap().parse::<usize>().unwrap()/2})).collect();
            ResponseTemplate::new(200).set_body_json(rows)
        }).mount(&server).await;
        let cfg = Config {
            base_url: server.uri(),
            ..Default::default()
        };
        for n in [1, 2, 8, 16, 24, 48] {
            let texts: Vec<_> = (0..n)
                .map(|i| format!("{i}:{}", "🔥".repeat(7996)))
                .collect();
            let order = rank(&reqwest::Client::new(), &cfg, "id", &texts, 16)
                .await
                .unwrap();
            let mut expected: Vec<_> = (0..n).collect();
            expected.sort_by_key(|i| std::cmp::Reverse(i / 2));
            assert_eq!(order, expected);
        }
    }

    #[tokio::test]
    async fn timeout_disconnect_and_duplicate_scores_are_errors() {
        use wiremock::{matchers::method, Mock, MockServer, ResponseTemplate};
        let server = MockServer::start().await;
        let cfg = Config {
            base_url: server.uri(),
            ..Default::default()
        };
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(Duration::from_millis(200))
            .build()
            .unwrap();
        let texts = ["one".into(), "two".into()];
        Mock::given(method("POST"))
            .respond_with(
                ResponseTemplate::new(200).set_body_json(
                    serde_json::json!([{"index":0,"score":1},{"index":0,"score":0}]),
                ),
            )
            .mount(&server)
            .await;
        assert_eq!(
            rank(&client, &cfg, "q", &texts, 2)
                .await
                .unwrap_err()
                .to_string(),
            "provider_invalid_scores"
        );
        server.reset().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(200).set_delay(Duration::from_secs(1)))
            .mount(&server)
            .await;
        assert_eq!(
            rank(&client, &cfg, "q", &texts, 2)
                .await
                .unwrap_err()
                .to_string(),
            "provider_timeout"
        );
        let socket = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let cfg = Config {
            base_url: format!("http://{}", socket.local_addr().unwrap()),
            ..Default::default()
        };
        drop(socket);
        assert!(rank(&client, &cfg, "q", &texts, 2).await.is_err());
    }

    #[tokio::test]
    async fn concurrent_search_and_saturated_model_recover() {
        use wiremock::{matchers::method, Mock, MockServer, ResponseTemplate};
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(429).insert_header("retry-after", "0"))
            .up_to_n_times(1)
            .with_priority(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(serde_json::json!([{"index":0,"score":1}])),
            )
            .expect(1)
            .mount(&server)
            .await;
        let cfg = Config {
            enabled: true,
            fallback: true,
            base_url: server.uri(),
            model: "test".into(),
        };
        let workspace = Uuid::now_v7();
        let slot = tokio::sync::Semaphore::new(1);
        let mut a = vec![ChunkView {
            id: Uuid::now_v7(),
            document_id: Uuid::now_v7(),
            seq: 0,
            filename: "fixture".into(),
            text: "synthetic".into(),
        }];
        let mut b = a.clone();
        let (left, right) = tokio::join!(
            apply_config(&cfg, workspace, "query", &mut a, &slot),
            apply_config(&cfg, workspace, "query", &mut b, &slot)
        );
        let mut statuses = [left.unwrap(), right.unwrap()];
        statuses.sort();
        assert_eq!(statuses, ["complete", "fallback"]);
        assert_eq!(a[0].id, b[0].id);
    }

    #[tokio::test]
    async fn failed_batches_never_publish_a_partial_order() {
        use wiremock::{matchers::method, Mock, MockServer, ResponseTemplate};
        for (status, body, calls) in [
            (429, "", 2),
            (503, "", 2),
            (422, "", 1),
            (200, "?", 1),
            (200, "[]", 1),
            (200, r#"[{"index":1,"score":1}]"#, 1),
            (200, r#"[{"index":0,"score":null}]"#, 1),
        ] {
            let server = MockServer::start().await;
            Mock::given(method("POST"))
                .respond_with(
                    ResponseTemplate::new(200)
                        .set_body_json(serde_json::json!([{"index":0,"score":1}])),
                )
                .up_to_n_times(1)
                .with_priority(1)
                .mount(&server)
                .await;
            Mock::given(method("POST"))
                .respond_with(
                    ResponseTemplate::new(status)
                        .set_body_string(body)
                        .insert_header("retry-after", "0"),
                )
                .expect(calls)
                .mount(&server)
                .await;
            let cfg = Config {
                base_url: server.uri(),
                ..Default::default()
            };
            assert!(rank(
                &reqwest::Client::new(),
                &cfg,
                "id",
                &["a".into(), "b".into()],
                1
            )
            .await
            .is_err());
        }
    }
}
