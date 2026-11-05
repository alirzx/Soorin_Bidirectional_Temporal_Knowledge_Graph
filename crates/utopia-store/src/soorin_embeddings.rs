//! Versioned document vectors. Unknown legacy vectors never match a new model.
use sha2::{Digest, Sha256};
use sqlx::PgPool;
use utopia_core::{models::LlmSettings, AppError, AppResult};
use uuid::Uuid;

pub fn identity(settings: &LlmSettings) -> String {
    let value = serde_json::json!([
        settings.embed_base_url,
        settings.embed_model,
        settings.embed_dim
    ]);
    let digest: String = Sha256::digest(value.to_string().as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    format!("sha256:{digest}")
}

pub async fn pending(
    pool: &PgPool,
    document: Uuid,
    settings: &LlmSettings,
) -> AppResult<Vec<(Uuid, String)>> {
    Ok(sqlx::query_as("SELECT id,text FROM chunks WHERE document_id=$1 AND superseded_at IS NULL AND (embedding IS NULL OR embedding_model IS DISTINCT FROM $2) ORDER BY seq")
        .bind(document).bind(identity(settings)).fetch_all(pool).await?)
}

pub async fn write(
    pool: &PgPool,
    items: &[(Uuid, Vec<f32>)],
    expected: &LlmSettings,
) -> AppResult<()> {
    let mut tx = pool.begin().await?;
    let current: LlmSettings =
        sqlx::query_as("SELECT * FROM llm_settings WHERE workspace_id=$1 FOR SHARE")
            .bind(expected.workspace_id)
            .fetch_one(&mut *tx)
            .await?;
    if identity(&current) != identity(expected) {
        return Err(AppError::Conflict(
            "embedding settings changed during inference; retry".into(),
        ));
    }
    let model = identity(expected);
    for (id, vector) in items {
        if vector.is_empty()
            || vector.iter().any(|v| !v.is_finite())
            || expected
                .embed_dim
                .is_some_and(|dim| vector.len() != dim as usize)
        {
            return Err(AppError::Validation(
                "embedding dimension or value invalid".into(),
            ));
        }
        sqlx::query("UPDATE chunks c SET embedding=$2,embedding_model=$3 FROM knowledge_bases k WHERE c.id=$1 AND k.id=c.kb_id AND k.workspace_id=$4 AND c.superseded_at IS NULL")
            .bind(id).bind(pgvector::Vector::from(vector.clone())).bind(&model).bind(expected.workspace_id).execute(&mut *tx).await?;
    }
    tx.commit().await?;
    if let Some((_, vector)) = items.first() {
        crate::vector_index::request(pool, crate::vector_index::Target::Chunks, vector.len())
            .await?;
    }
    Ok(())
}
