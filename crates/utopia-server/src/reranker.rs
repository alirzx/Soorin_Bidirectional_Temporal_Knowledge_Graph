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

#[derive(Default)]
struct BatchStats {
    count: usize,
}

pub struct Report {
    pub status: &'static str,
    pub candidates: usize,
    pub batches: usize,
    pub fallback_reason: Option<String>,
}

impl Report {
    pub fn order(&self, authorized: usize) -> &'static str {
        match self.status {
            "complete" if self.candidates < authorized => "cross_encoder_then_rank_fusion",
            "complete" => "cross_encoder",
            _ => "rank_fusion",
        }
    }
}

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
    stats: &mut BatchStats,
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
            }))
            .map_err(|_| anyhow::anyhow!("provider_request_encoding"))?;
            if bytes.len() <= MAX_BODY {
                break bytes;
            }
            anyhow::ensure!(end > start + 1, "provider_request_size");
            end = start + (end - start) / 2;
        };
        stats.count += 1;
        let mut response = loop {
            let started = std::time::Instant::now();
            let provider_request_id = Uuid::now_v7();
            let reply = client
                .post(&url)
                .header("Content-Type", "application/json")
                .header("X-Request-Id", provider_request_id.to_string())
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
            tracing::debug!(%provider_request_id, status, batch = stats.count, batch_size = end-start,
                provider_elapsed_ms = started.elapsed().as_millis(), "search.rerank_batch_received");
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
            if status == 429
                && reply
                    .headers()
                    .get("x-soorin-rejection")
                    .and_then(|v| v.to_str().ok())
                    == Some("queue_timeout")
            {
                anyhow::bail!("queue_timeout");
            }
            anyhow::ensure!(reply.status().is_success(), "provider_http_{status}");
            break reply;
        };
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|err| {
            if err.is_timeout() {
                anyhow::anyhow!("provider_timeout")
            } else {
                anyhow::anyhow!("provider_read")
            }
        })? {
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

fn setting(name: &str, default: usize, min: usize, max: usize) -> usize {
    bounded(std::env::var(name).ok().as_deref(), default, min, max)
}

pub fn deadline_seconds() -> u64 {
    setting("SOORIN_RERANK_DEADLINE_SECONDS", 30, 5, 180) as u64
}

pub async fn apply(
    pool: &sqlx::PgPool,
    workspace: Uuid,
    query: &str,
    chunks: &mut [ChunkView],
) -> anyhow::Result<Report> {
    let cfg = config(pool, workspace).await?;
    let candidates = setting("SOORIN_RERANK_MAX_CANDIDATES", 16, 1, 48);
    apply_config(&cfg, query, chunks, &SEARCH_SLOT, candidates).await
}

async fn apply_config(
    cfg: &Config,
    query: &str,
    chunks: &mut [ChunkView],
    slot: &tokio::sync::Semaphore,
    candidates: usize,
) -> anyhow::Result<Report> {
    if !cfg.enabled || chunks.is_empty() {
        return Ok(Report {
            status: "disabled",
            candidates: 0,
            batches: 0,
            fallback_reason: None,
        });
    }
    let batch_size = setting("SOORIN_RERANK_BATCH_SIZE", 8, 1, 16);
    let timeout_seconds =
        (setting("SOORIN_RERANK_TIMEOUT_SECONDS", 18, 5, 180) as u64).min(deadline_seconds());
    let window = chunks.len().min(candidates);
    let started = std::time::Instant::now();
    let mut stats = BatchStats::default();
    tracing::debug!(
        rerank_candidate_count = window,
        candidate_count = chunks.len(),
        batch_size,
        model_role = "reranker",
        "search.rerank_started"
    );
    let result: anyhow::Result<Vec<usize>> = async {
        utopia_llm::egress::require(&cfg.base_url)
            .map_err(|_| anyhow::anyhow!("egress_blocked"))?;
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(timeout_seconds))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| anyhow::anyhow!("client_configuration"))?;
        let _permit = slot
            .try_acquire()
            .map_err(|_| anyhow::anyhow!("search_capacity"))?;
        let texts: Vec<String> = chunks[..window]
            .iter()
            .map(|c| c.text.trim().chars().take(8000).collect())
            .collect();
        let query: String = query.trim().chars().take(4000).collect();
        tokio::time::timeout(
            Duration::from_secs(deadline_seconds()),
            rank(&http, cfg, &query, &texts, batch_size, &mut stats),
        )
        .await
        .map_err(|_| anyhow::anyhow!("rerank_deadline"))?
    }
    .await;
    match result {
        Ok(order) => {
            let original = chunks[..window].to_vec();
            for (chunk, index) in chunks[..window].iter_mut().zip(order) {
                chunk.clone_from(&original[index]);
            }
            tracing::debug!(
                rerank_candidate_count = window,
                batch_count = stats.count,
                duration_ms = started.elapsed().as_millis(),
                "search.rerank_completed"
            );
            Ok(Report {
                status: "complete",
                candidates: window,
                batches: stats.count,
                fallback_reason: None,
            })
        }
        Err(error) => {
            // rank returns controlled categories, never provider response text.
            tracing::warn!(fallback_reason = %error, rerank_candidate_count = window,
                batch_count = stats.count, duration_ms = started.elapsed().as_millis(),
                fallback_enabled = cfg.fallback, "search.rerank_fallback");
            if cfg.fallback {
                Ok(Report {
                    status: "fallback",
                    candidates: window,
                    batches: stats.count,
                    fallback_reason: Some(error.to_string()),
                })
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
            let order = rank(
                &reqwest::Client::new(),
                &cfg,
                "id",
                &texts,
                16,
                &mut BatchStats::default(),
            )
            .await
            .unwrap();
            let mut expected: Vec<_> = (0..n).collect();
            expected.sort_by_key(|i| std::cmp::Reverse(i / 2));
            assert_eq!(order, expected);
        }
    }

    #[tokio::test]
    async fn a_large_result_set_keeps_its_rrf_tail() {
        use wiremock::{matchers::path, Mock, MockServer, Request, ResponseTemplate};
        let server = MockServer::start().await;
        Mock::given(path("/rerank"))
            .respond_with(|req: &Request| {
                let body: serde_json::Value = req.body_json().unwrap();
                let rows: Vec<_> = body["texts"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .enumerate()
                    .map(|(index, text)| {
                        let seq: usize = text.as_str().unwrap().parse().unwrap();
                        assert!(seq < 16);
                        serde_json::json!({"index": index, "score": seq})
                    })
                    .collect();
                ResponseTemplate::new(200).set_body_json(rows)
            })
            .expect(4)
            .mount(&server)
            .await;
        let cfg = Config {
            enabled: true,
            fallback: true,
            base_url: server.uri(),
            model: "mock".into(),
        };
        let slot = tokio::sync::Semaphore::new(1);
        for top_k in [1, 30] {
            let mut chunks: Vec<_> = (0..48)
                .map(|seq| ChunkView {
                    id: Uuid::now_v7(),
                    document_id: Uuid::now_v7(),
                    seq,
                    filename: "fixture".into(),
                    text: seq.to_string(),
                })
                .collect();
            let report = apply_config(&cfg, "query", &mut chunks, &slot, 16)
                .await
                .unwrap();
            assert_eq!(report.status, "complete");
            assert_eq!((report.candidates, report.batches), (16, 2));
            assert_eq!(report.order(48), "cross_encoder_then_rank_fusion");
            chunks.truncate(top_k);
            let expected: Vec<_> = (0..16).rev().chain(16..48).take(top_k).collect();
            assert_eq!(
                chunks.iter().map(|chunk| chunk.seq).collect::<Vec<_>>(),
                expected
            );
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
            rank(&client, &cfg, "q", &texts, 2, &mut BatchStats::default())
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
            rank(&client, &cfg, "q", &texts, 2, &mut BatchStats::default())
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
        assert!(
            rank(&client, &cfg, "q", &texts, 2, &mut BatchStats::default())
                .await
                .is_err()
        );
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
            apply_config(&cfg, "query", &mut a, &slot, 16),
            apply_config(&cfg, "query", &mut b, &slot, 16)
        );
        let mut statuses = [left.unwrap().status, right.unwrap().status];
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
                1,
                &mut BatchStats::default(),
            )
            .await
            .is_err());
        }
    }
}
