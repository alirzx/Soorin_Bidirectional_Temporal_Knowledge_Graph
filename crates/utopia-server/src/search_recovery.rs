//! Bounded, restartable derived-index recovery. PostgreSQL remains authoritative.
use futures_util::TryStreamExt;
use std::io::Write;
use std::path::Path;
use utopia_search::SearchIndex;

const MARKER: &str = ".soorin-jieba-lowercase-v3";
const VERSION: &[u8] = b"jieba-lowercase-v3-live-documents\n";
const BATCH_BYTES: usize = 2 * 1024 * 1024;
const BATCH_ROWS: usize = 256;

pub struct Recovery {
    pub rebuilt: bool,
    pub chunks: usize,
}

pub async fn recover(
    pool: &sqlx::PgPool,
    search: &SearchIndex,
    index_dir: &Path,
) -> anyhow::Result<Recovery> {
    let marker = index_dir.join(MARKER);
    let valid_marker = std::fs::read(&marker).is_ok_and(|bytes| bytes == VERSION);
    let live_chunks = utopia_store::documents::live_chunk_count(pool).await?;
    if valid_marker && search.len() as i64 == live_chunks {
        return Ok(Recovery {
            rebuilt: false,
            chunks: search.len(),
        });
    }
    rebuild(
        search,
        index_dir,
        utopia_store::documents::stream_chunks_for_index(pool),
    )
    .await
}

async fn rebuild(
    search: &SearchIndex,
    index_dir: &Path,
    mut stream: impl futures_util::TryStream<Ok = utopia_store::documents::IndexChunk, Error = sqlx::Error>
        + Unpin,
) -> anyhow::Result<Recovery> {
    let marker = index_dir.join(MARKER);
    // Invalidate before clearing so a crash cannot leave a valid marker over a
    // partial index. Remove only this derived marker, never source data.
    if marker.exists() {
        std::fs::remove_file(&marker)?;
    }
    search.clear_for_recovery()?;
    let mut batch = Vec::new();
    let mut bytes = 0;
    let mut chunks = 0;
    while let Some((kb, document, chunk, text)) = stream.try_next().await? {
        bytes += text.len();
        batch.push((
            kb.to_string(),
            document.to_string(),
            chunk.to_string(),
            text,
        ));
        chunks += 1;
        if batch.len() >= BATCH_ROWS || bytes >= BATCH_BYTES {
            search.append_recovery_batch(&batch)?;
            batch.clear();
            bytes = 0;
        }
    }
    if !batch.is_empty() {
        search.append_recovery_batch(&batch)?;
    }
    let temporary = index_dir.join(format!("{MARKER}.pending"));
    let mut file = std::fs::File::create(&temporary)?;
    file.write_all(VERSION)?;
    file.sync_all()?;
    std::fs::rename(temporary, marker)?;
    // Persist the rename as well as the marker content on the Linux deployment.
    #[cfg(unix)]
    std::fs::File::open(index_dir)?.sync_all()?;
    Ok(Recovery {
        rebuilt: true,
        chunks,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    #[tokio::test]
    async fn empty_source_and_failed_stream_leave_truthful_markers() -> anyhow::Result<()> {
        let directory = tempfile::tempdir()?;
        let index = SearchIndex::open(directory.path())?;
        let empty = futures_util::stream::iter(Vec::<
            Result<utopia_store::documents::IndexChunk, sqlx::Error>,
        >::new());
        let report = rebuild(&index, directory.path(), empty).await?;
        assert!(report.rebuilt && report.chunks == 0 && index.is_empty());
        assert_eq!(std::fs::read(directory.path().join(MARKER))?, VERSION);
        let kb = Uuid::now_v7();
        let doc = Uuid::now_v7();
        let mut rows: Vec<_> = (0..257)
            .map(|_| Ok((kb, doc, Uuid::now_v7(), "PartialOnlyToken".into())))
            .collect();
        rows.push(Err(sqlx::Error::Protocol("injected stream failure".into())));
        assert!(
            rebuild(&index, directory.path(), futures_util::stream::iter(rows))
                .await
                .is_err()
        );
        assert!(!directory.path().join(MARKER).exists());
        let chunk = Uuid::now_v7();
        let rows = vec![Ok((kb, doc, chunk, "Recovered source title".into()))];
        rebuild(&index, directory.path(), futures_util::stream::iter(rows)).await?;
        assert!(index
            .search(&kb.to_string(), "PartialOnlyToken", 10)?
            .is_empty());
        assert_eq!(
            index.search(&kb.to_string(), "Recovered", 10)?[0].chunk_id,
            chunk.to_string()
        );
        Ok(())
    }

    #[tokio::test]
    async fn migration_retries_partial_indexes_excludes_deleted_and_preserves_citations(
    ) -> anyhow::Result<()> {
        let Some(url) = utopia_store::test_db::url() else {
            return Ok(());
        };
        // Recovery intentionally reads every KB. Other workspace tests write
        // concurrently, so a shared fixture DB cannot prove stable-count
        // restart idempotency. Use a dedicated disposable database instead.
        let admin = sqlx::PgPool::connect(&url).await?;
        let database = format!("soorin_index_{}", Uuid::now_v7().simple());
        sqlx::query(&format!("CREATE DATABASE {database}"))
            .execute(&admin)
            .await?;
        let options = url
            .parse::<sqlx::postgres::PgConnectOptions>()?
            .database(&database);
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect_with(options)
            .await?;
        utopia_store::db::migrate(&pool).await?;
        let (org, ws, kb, doc, deleted, chunk, old) = (
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
        );
        sqlx::raw_sql(&format!("INSERT INTO organizations(id,name) VALUES('{org}','index-recovery');
          INSERT INTO workspaces(id,org_id,name) VALUES('{ws}','{org}','index-recovery');
          INSERT INTO knowledge_bases(id,workspace_id,name) VALUES('{kb}','{ws}','index-recovery');
          INSERT INTO documents(id,kb_id,filename,sha256) VALUES('{doc}','{kb}','synthetic.json','{doc}'),('{deleted}','{kb}','deleted.json','{deleted}');
          INSERT INTO chunks(id,kb_id,document_id,seq,text) VALUES('{chunk}','{kb}','{doc}',0,'Password Spray Detection synthetic source evidence'),('{old}','{kb}','{deleted}',0,'DeletedOnlyToken');
          UPDATE documents SET deleted_at=now() WHERE id='{deleted}';" )).execute(&pool).await?;
        let result: anyhow::Result<()> = async {
            let directory = tempfile::tempdir()?;
            let index = SearchIndex::open(directory.path())?;
            index.reindex_document(
                &kb.to_string(),
                &deleted.to_string(),
                &[(old.to_string(), "DeletedOnlyToken".into())],
            )?;
            std::fs::write(directory.path().join(MARKER), b"corrupt")?;
            let report = recover(&pool, &index, directory.path()).await?;
            assert!(report.rebuilt);
            let hits = index.search(&kb.to_string(), "password spray detection", 10)?;
            assert_eq!(hits.len(), 1);
            assert_eq!(hits[0].chunk_id, chunk.to_string());
            assert!(index
                .search(&kb.to_string(), "DeletedOnlyToken", 10)?
                .is_empty());
            assert!(index
                .search(&Uuid::now_v7().to_string(), "Password", 10)?
                .is_empty());
            assert!(!recover(&pool, &index, directory.path()).await?.rebuilt);
            // Interrupted conversion: no marker + a partially written posting.
            std::fs::remove_file(directory.path().join(MARKER))?;
            index.clear_for_recovery()?;
            index.append_recovery_batch(&[(
                kb.to_string(),
                doc.to_string(),
                "orphan-chunk".into(),
                "OrphanToken".into(),
            )])?;
            assert!(recover(&pool, &index, directory.path()).await?.rebuilt);
            assert!(index.search(&kb.to_string(), "OrphanToken", 10)?.is_empty());
            assert_eq!(
                index.search(&kb.to_string(), "PASSWORD", 10)?[0].chunk_id,
                chunk.to_string()
            );
            Ok(())
        }
        .await;
        pool.close().await;
        sqlx::query(&format!("DROP DATABASE {database}"))
            .execute(&admin)
            .await?;
        result
    }
}
