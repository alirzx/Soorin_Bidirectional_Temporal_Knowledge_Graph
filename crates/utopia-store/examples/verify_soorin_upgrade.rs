//! Acceptance utility: refuses initialized databases; upgrades a disposable
//! baseline through 0112, preserving a synthetic document and migration hashes.
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let url = std::env::var("UTOPIA_DATABASE_URL")?;
    let pool = utopia_store::db::connect(&url, Some(2)).await?;
    let initialized:bool=sqlx::query_scalar("SELECT to_regclass('_sqlx_migrations') IS NOT NULL OR to_regclass('organizations') IS NOT NULL").fetch_one(&pool).await?;
    anyhow::ensure!(
        !initialized,
        "refusing initialized database; provide a NEW disposable database"
    );
    let baseline = tempfile::tempdir()?;
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../migrations");
    for entry in std::fs::read_dir(root)? {
        let path = entry?.path();
        let name = path.file_name().unwrap().to_str().unwrap();
        if path.extension().and_then(|v| v.to_str()) == Some("sql")
            && name.split('_').next().unwrap().parse::<i64>()? <= 112
        {
            std::fs::copy(&path, baseline.path().join(name))?;
        }
    }
    sqlx::migrate::Migrator::new(baseline.path())
        .await?
        .run(&pool)
        .await?;
    let before: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await?;
    let (org, ws, kb, doc) = (
        uuid::Uuid::now_v7(),
        uuid::Uuid::now_v7(),
        uuid::Uuid::now_v7(),
        uuid::Uuid::now_v7(),
    );
    sqlx::raw_sql(&format!("INSERT INTO organizations(id,name) VALUES('{org}','synthetic-upgrade');INSERT INTO workspaces(id,org_id,name) VALUES('{ws}','{org}','synthetic-upgrade');INSERT INTO knowledge_bases(id,workspace_id,name) VALUES('{kb}','{ws}','synthetic-upgrade');INSERT INTO documents(id,kb_id,filename,sha256) VALUES('{doc}','{kb}','synthetic-preserved.txt',repeat('0',64));")).execute(&pool).await?;
    utopia_store::db::migrate(&pool).await?;
    utopia_store::db::migrate(&pool).await?;
    let after: Vec<(i64, Vec<u8>)> = sqlx::query_as(
        "SELECT version,checksum FROM _sqlx_migrations WHERE version<=112 ORDER BY version",
    )
    .fetch_all(&pool)
    .await?;
    anyhow::ensure!(
        before == after,
        "applied historical migration checksum changed"
    );
    let preserved: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM documents WHERE id=$1 AND filename='synthetic-preserved.txt')",
    )
    .bind(doc)
    .fetch_one(&pool)
    .await?;
    anyhow::ensure!(preserved, "synthetic document not preserved");
    println!("PASS: baseline {} migrations preserved; upgrade applied twice; synthetic document preserved",before.len());
    pool.close().await;
    Ok(())
}
