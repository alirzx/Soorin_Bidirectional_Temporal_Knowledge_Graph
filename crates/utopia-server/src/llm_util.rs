//! 从工作区设置构造 LLM 客户端，以及按模型的并发闸门。

use std::collections::HashMap;
use std::sync::Arc;

use tokio::sync::{OwnedSemaphorePermit, Semaphore};
use utopia_core::models::LlmSettings;
use utopia_llm::LlmClient;

use crate::state::AppState;

pub fn chat_client(s: &LlmSettings) -> Option<LlmClient> {
    if !s.chat_ready() {
        return None;
    }
    Some(
        LlmClient::with_timeouts(
            s.chat_base_url.as_deref()?,
            s.chat_api_key.as_deref(),
            s.chat_model.as_deref()?,
            std::time::Duration::from_secs(10),
            std::time::Duration::from_secs(s.chat_timeout_seconds.clamp(1, 3600) as u64),
        )
        .with_reasoning_effort(s.chat_reasoning_effort.clone())
        .with_gateway_from_env(&s.workspace_id.to_string()),
    )
}

/// 对话模型的设置：地址、密钥、模型、推理力度。任一项变了就是另一个客户端
type ChatConfig = (
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
    i32,
);

/// 各工作区的对话客户端，跨轮次留着。
///
/// 端点报过的上下文窗口记在客户端上（`LlmClient::remember_context_window`），每轮新建一个
/// 就等于每轮都忘，下一轮照样撞上同一个 400（#964）。模型设置一变就换新的：学到的窗口
/// 是那个模型的，不是这个工作区的。密钥和窗口都不跨工作区
#[derive(Default)]
pub struct ConversationClients {
    inner: std::sync::Mutex<HashMap<uuid::Uuid, (ChatConfig, LlmClient)>>,
}

impl ConversationClients {
    pub fn get(&self, workspace: uuid::Uuid, s: &LlmSettings) -> Option<LlmClient> {
        let mut clients = self.inner.lock().unwrap();
        if !s.chat_ready() {
            clients.remove(&workspace);
            return None;
        }
        let config = (
            s.chat_base_url.clone(),
            s.chat_api_key.clone(),
            s.chat_model.clone(),
            s.chat_reasoning_effort.clone(),
            s.chat_timeout_seconds,
        );
        if let Some((previous, client)) = clients.get(&workspace) {
            if previous == &config {
                return Some(client.clone());
            }
        }
        let client = chat_client(s)?;
        clients.insert(workspace, (config, client.clone()));
        Some(client)
    }
}

/// 一轮对话里嵌过的文字与它的向量（#971）。挑口径、检索分块、按名字查实体都要把问题嵌成
/// 向量，一轮之内是同一句话、同一个模型，嵌一次就够。缓存跟着这一轮的 `ToolSink` 走，不落库，
/// 只记成功的；没有这一轮的调用方（HTTP 检索、口径页）传 `None`，各嵌各的
#[derive(Default)]
pub struct EmbedCache {
    vectors: HashMap<(uuid::Uuid, String, String), Vec<f32>>,
}

impl EmbedCache {
    fn key(settings: &LlmSettings, text: &str) -> (uuid::Uuid, String, String) {
        // Exact text is intentional: whitespace and case can affect model output.
        (
            settings.workspace_id,
            utopia_store::soorin_embeddings::identity(settings),
            text.to_owned(),
        )
    }

    pub fn valid(settings: &LlmSettings, vector: &[f32]) -> bool {
        !vector.is_empty()
            && vector.iter().all(|v| v.is_finite())
            && settings
                .embed_dim
                .is_none_or(|dim| dim > 0 && vector.len() == dim as usize)
    }

    pub fn get(&self, settings: &LlmSettings, text: &str) -> Option<&Vec<f32>> {
        self.vectors
            .get(&Self::key(settings, text))
            .filter(|v| Self::valid(settings, v))
    }

    pub fn insert(&mut self, settings: &LlmSettings, text: &str, vector: Vec<f32>) {
        if Self::valid(settings, &vector) {
            self.vectors.insert(Self::key(settings, text), vector);
        }
    }
}

#[cfg(test)]
mod cache_tests {
    use super::*;

    #[test]
    fn cache_separates_workspace_model_dimension_and_exact_text_and_rejects_invalid_vectors() {
        let mut settings = LlmSettings {
            workspace_id: uuid::Uuid::now_v7(),
            embed_base_url: Some("http://synthetic:8080/v1".into()),
            embed_model: Some("synthetic@revision1".into()),
            embed_dim: Some(2),
            embed_api_key: None,
            updated_at: chrono::Utc::now(),
            ocr_provider: "mineru".into(),
            chat_base_url: None,
            chat_api_key: None,
            chat_model: None,
            chat_reasoning_effort: None,
            chat_timeout_seconds: 300,
            ocr_base_url: None,
            ocr_api_key: None,
            ocr_backend: None,
            ocr_model: None,
            transcribe_base_url: None,
            transcribe_api_key: None,
            transcribe_model: None,
        };
        let mut cache = EmbedCache::default();
        cache.insert(&settings, "Host A", vec![1.0, 0.0]);
        assert_eq!(cache.get(&settings, "Host A"), Some(&vec![1.0, 0.0]));
        assert!(cache.get(&settings, "Host B").is_none());
        assert!(cache.get(&settings, " Host A").is_none());
        let workspace = settings.workspace_id;
        settings.workspace_id = uuid::Uuid::now_v7();
        assert!(cache.get(&settings, "Host A").is_none());
        settings.workspace_id = workspace;
        settings.embed_model = Some("synthetic@revision2".into());
        assert!(cache.get(&settings, "Host A").is_none());
        settings.embed_model = Some("synthetic@revision1".into());
        settings.embed_dim = Some(3);
        assert!(cache.get(&settings, "Host A").is_none());
        settings.embed_dim = Some(2);
        for invalid in [
            vec![],
            vec![1.0],
            vec![f32::NAN, 0.0],
            vec![f32::INFINITY, 0.0],
        ] {
            cache.insert(&settings, "bad", invalid);
            assert!(cache.get(&settings, "bad").is_none());
        }
        // A failed request inserts nothing and cannot poison an existing success.
        assert_eq!(cache.get(&settings, "Host A"), Some(&vec![1.0, 0.0]));
    }
}

pub fn embed_client(s: &LlmSettings) -> Option<LlmClient> {
    if !s.embed_ready() {
        return None;
    }
    Some(
        LlmClient::new(
            s.embed_base_url.as_deref()?,
            s.embed_api_key.as_deref(),
            s.embed_model.as_deref()?,
        )
        .with_gateway_from_env(&s.workspace_id.to_string()),
    )
}

/// 按模型的信号量注册表。限额变了就换一把新的——旧的在飞许可自然跑完，
/// 换的瞬间可能短暂超出新限额，可接受；换来的是"改完即时生效"而不必做
/// 缓存失效，也不必和 tokio Semaphore 不能缩容的限制搏斗。
#[derive(Default)]
pub struct ModelGates {
    inner: std::sync::Mutex<HashMap<String, (usize, Arc<Semaphore>)>>,
}

impl ModelGates {
    fn gate(&self, key: &str, limit: usize) -> Arc<Semaphore> {
        let mut m = self.inner.lock().unwrap();
        match m.get(key) {
            Some((n, sem)) if *n == limit => sem.clone(),
            _ => {
                let sem = Arc::new(Semaphore::new(limit));
                m.insert(key.to_string(), (limit, sem.clone()));
                sem
            }
        }
    }
}

/// 后台任务调模型前取一张许可，持有到调用结束。
///
/// **只给后台任务用**（抽取、裁决、摄入嵌入、本体建议）。用户的对话与检索
/// 不走这里——让人打字等在十个后台抽取后面，产品就成了坏的；真正会打爆
/// 供应商速率限制的也从来不是一个人在打字。
///
/// 限额读不到（表还没建、库暂时不可达）时**放行**：并发限制是保护措施，
/// 不该因为读不到配置而把整条流水线卡死。
pub async fn acquire(
    state: &AppState,
    base_url: &str,
    model: &str,
) -> Option<OwnedSemaphorePermit> {
    let limit = utopia_store::model_limits::limit_for(&state.pool, base_url, model)
        .await
        .ok()?;
    let key = format!("{base_url}|{model}");
    state
        .model_gates
        .gate(&key, limit)
        .acquire_owned()
        .await
        .ok()
}

/// `acquire` 的便捷形式：直接从工作区设置取 chat 模型的身份。
pub async fn acquire_chat(state: &AppState, s: &LlmSettings) -> Option<OwnedSemaphorePermit> {
    let (base, model) = (s.chat_base_url.as_deref()?, s.chat_model.as_deref()?);
    acquire(state, base, model).await
}

/// `acquire` 的便捷形式：embedding 模型。
pub async fn acquire_embed(state: &AppState, s: &LlmSettings) -> Option<OwnedSemaphorePermit> {
    let (base, model) = (s.embed_base_url.as_deref()?, s.embed_model.as_deref()?);
    acquire(state, base, model).await
}
