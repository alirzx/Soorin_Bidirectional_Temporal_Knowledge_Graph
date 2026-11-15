//! Real-database tests for authoritative SOC identity resolution.
//! Uses a dedicated KB on TEST_DATABASE_URL; never point test_db at a user QA database.
use sqlx::PgPool;
use utopia_store::resolution::resolve_curated_canonical;
use uuid::Uuid;

#[tokio::test]
async fn shared_soc_case_keeps_one_typed_entity_across_documents() -> anyhow::Result<()> {
    let Some(url) = utopia_store::test_db::url() else {
        return Ok(());
    };
    let pool = PgPool::connect(&url).await?;
    utopia_store::db::migrate(&pool).await?;

    let (org, ws, kb, kind) = (
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
        Uuid::now_v7(),
    );
    sqlx::query("INSERT INTO organizations(id,name) VALUES($1,'soc-canonical-test')")
        .bind(org)
        .execute(&pool)
        .await?;
    sqlx::query("INSERT INTO workspaces(id,org_id,name) VALUES($1,$2,'soc-canonical-test')")
        .bind(ws)
        .bind(org)
        .execute(&pool)
        .await?;
    sqlx::query(
        "INSERT INTO knowledge_bases(id,workspace_id,name) VALUES($1,$2,'soc-canonical-test')",
    )
    .bind(kb)
    .bind(ws)
    .execute(&pool)
    .await?;
    sqlx::query("INSERT INTO entity_types(id,kb_id,key,label) VALUES($1,$2,'soc_case','SOCCase')")
        .bind(kind)
        .bind(kb)
        .execute(&pool)
        .await?;

    let run = async {
        let key = "soorin:soccase:synthetic-shared-case";
        let (a,b) = tokio::join!(
            resolve_curated_canonical(&pool,kb,key,"SOCCase"),
            resolve_curated_canonical(&pool,kb,key,"SOCCase"),
        );
        let a=a?;
        let b=b?;
        anyhow::ensure!(a==b,"parallel receipts created different canonical entities");
        let row:(Option<Uuid>,String)=sqlx::query_as(
            "SELECT type_id, specific_type FROM entities WHERE id=$1")
            .bind(a).fetch_one(&pool).await?;
        anyhow::ensure!(row.0 == Some(kind) && row.1=="SOCCase","canonical type not installed");
        let count:i64=sqlx::query_scalar(
            "SELECT count(*) FROM entities WHERE kb_id=$1 AND canonical_name=$2 AND merged_into IS NULL")
            .bind(kb).bind(key).fetch_one(&pool).await?;
        anyhow::ensure!(count==1,"shared case key has {count} entities, expected one");

        // A different authoritative type is a conflict, not an implicit retag.
        let bad=resolve_curated_canonical(&pool,kb,key,"WrongKind").await;
        anyhow::ensure!(bad.is_err(),"unknown kind was accepted");
        // Regression: no automatic merging of previously corrupted identities.
        let duplicate=Uuid::now_v7();
        sqlx::query("INSERT INTO entities(id,kb_id,canonical_name) VALUES($1,$2,$3)")
            .bind(duplicate).bind(kb).bind(key).execute(&pool).await?;
        let ambiguous=resolve_curated_canonical(&pool,kb,key,"SOCCase").await;
        anyhow::ensure!(ambiguous.is_err(),"ambiguous old identity should require human review");
        Ok::<_,anyhow::Error>(())
    }.await;
    sqlx::query("DELETE FROM organizations WHERE id=$1")
        .bind(org)
        .execute(&pool)
        .await?;
    pool.close().await;
    run
}
