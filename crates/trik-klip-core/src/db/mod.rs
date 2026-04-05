// SQLite database layer — pool init, migrations, queries.
// Adapted from MEEM Dashboard db/mod.rs pattern.

use anyhow::Context;
use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions};
use sqlx::{Row, SqlitePool};
use tracing::info;

pub mod models;

use models::*;

/// Initialize the SQLite connection pool.
///
/// Creates parent directories if needed, enables WAL mode, and runs migrations.
pub async fn init_pool(db_path: &str) -> anyhow::Result<SqlitePool> {
    // Ensure parent directory exists
    if let Some(parent) = std::path::Path::new(db_path).parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("Failed to create db directory: {}", parent.display()))?;
    }

    let options = SqliteConnectOptions::new()
        .filename(db_path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal);

    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(options)
        .await
        .with_context(|| format!("Failed to connect to database: {}", db_path))?;

    run_migrations(&pool).await?;

    info!("Database initialized at {}", db_path);
    Ok(pool)
}

/// Create all required tables if they do not already exist.
pub async fn run_migrations(pool: &SqlitePool) -> anyhow::Result<()> {
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS transcripts (
            id TEXT PRIMARY KEY,
            file_hash TEXT UNIQUE NOT NULL,
            source_path TEXT NOT NULL,
            segments_json TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            whisper_model TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'en',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        "#,
    )
    .execute(pool)
    .await?;

    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS clip_results (
            id TEXT PRIMARY KEY,
            transcript_id TEXT NOT NULL REFERENCES transcripts(id),
            clips_json TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            custom_prompts TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        "#,
    )
    .execute(pool)
    .await?;

    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS provider_profiles (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            api_key TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        "#,
    )
    .execute(pool)
    .await?;

    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        "#,
    )
    .execute(pool)
    .await?;

    Ok(())
}

// ── Transcript queries ─────────────────────────────────────────────────────

/// Look up a transcript by its file hash.
pub async fn get_transcript_by_hash(
    pool: &SqlitePool,
    file_hash: &str,
) -> anyhow::Result<Option<TranscriptRow>> {
    let row = sqlx::query_as::<_, TranscriptRow>(
        "SELECT id, file_hash, source_path, segments_json, duration_seconds, \
         whisper_model, language, created_at FROM transcripts WHERE file_hash = ?",
    )
    .bind(file_hash)
    .fetch_optional(pool)
    .await?;
    Ok(row)
}

/// Insert or replace a transcript row. Generates a new UUID if `row.id` is empty.
pub async fn save_transcript(pool: &SqlitePool, row: &TranscriptRow) -> anyhow::Result<()> {
    let id = if row.id.is_empty() {
        uuid::Uuid::new_v4().to_string()
    } else {
        row.id.clone()
    };

    sqlx::query(
        "INSERT OR REPLACE INTO transcripts \
         (id, file_hash, source_path, segments_json, duration_seconds, whisper_model, language) \
         VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(&row.file_hash)
    .bind(&row.source_path)
    .bind(&row.segments_json)
    .bind(row.duration_seconds)
    .bind(&row.whisper_model)
    .bind(&row.language)
    .execute(pool)
    .await?;
    Ok(())
}

// ── Clip result queries ────────────────────────────────────────────────────

/// Save a clip analysis result set.
pub async fn save_clip_result(pool: &SqlitePool, row: &ClipResultRow) -> anyhow::Result<()> {
    let id = if row.id.is_empty() {
        uuid::Uuid::new_v4().to_string()
    } else {
        row.id.clone()
    };

    sqlx::query(
        "INSERT OR REPLACE INTO clip_results \
         (id, transcript_id, clips_json, provider, model, custom_prompts) \
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(&row.transcript_id)
    .bind(&row.clips_json)
    .bind(&row.provider)
    .bind(&row.model)
    .bind(&row.custom_prompts)
    .execute(pool)
    .await?;
    Ok(())
}

// ── Provider profile queries ───────────────────────────────────────────────

/// List all saved provider profiles, ordered by name.
pub async fn list_provider_profiles(pool: &SqlitePool) -> anyhow::Result<Vec<ProviderProfileRow>> {
    let rows = sqlx::query_as::<_, ProviderProfileRow>(
        "SELECT id, name, provider, model, api_key, base_url, is_default, created_at \
         FROM provider_profiles ORDER BY name",
    )
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

/// Insert or replace a provider profile. Generates a new UUID if `row.id` is empty.
pub async fn save_provider_profile(
    pool: &SqlitePool,
    row: &ProviderProfileRow,
) -> anyhow::Result<()> {
    let id = if row.id.is_empty() {
        uuid::Uuid::new_v4().to_string()
    } else {
        row.id.clone()
    };

    sqlx::query(
        "INSERT OR REPLACE INTO provider_profiles \
         (id, name, provider, model, api_key, base_url, is_default) \
         VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(&row.name)
    .bind(&row.provider)
    .bind(&row.model)
    .bind(&row.api_key)
    .bind(&row.base_url)
    .bind(row.is_default)
    .execute(pool)
    .await?;
    Ok(())
}

/// Delete a provider profile by ID.
pub async fn delete_provider_profile(pool: &SqlitePool, id: &str) -> anyhow::Result<()> {
    sqlx::query("DELETE FROM provider_profiles WHERE id = ?")
        .bind(id)
        .execute(pool)
        .await?;
    Ok(())
}

// ── System state (key-value) ───────────────────────────────────────────────

/// Get a value from the system_state table.
pub async fn get_system_state(pool: &SqlitePool, key: &str) -> anyhow::Result<Option<String>> {
    let row = sqlx::query("SELECT value FROM system_state WHERE key = ?")
        .bind(key)
        .fetch_optional(pool)
        .await?;
    Ok(row.map(|r| r.get::<String, _>("value")))
}

/// Set a value in the system_state table (upsert).
pub async fn set_system_state(pool: &SqlitePool, key: &str, value: &str) -> anyhow::Result<()> {
    sqlx::query(
        "INSERT INTO system_state (key, value, updated_at) VALUES (?, ?, datetime('now')) \
         ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
    )
    .bind(key)
    .bind(value)
    .execute(pool)
    .await?;
    Ok(())
}
