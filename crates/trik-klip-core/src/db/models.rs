// Database row structs for SQLite.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct TranscriptRow {
    pub id: String,
    pub file_hash: String,
    pub source_path: String,
    pub segments_json: String,
    pub duration_seconds: f64,
    pub whisper_model: String,
    pub language: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct ClipResultRow {
    pub id: String,
    pub transcript_id: String,
    pub clips_json: String,
    pub provider: String,
    pub model: String,
    pub custom_prompts: Option<String>,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct ProviderProfileRow {
    pub id: String,
    pub name: String,
    pub provider: String,
    pub model: String,
    pub api_key: String,
    pub base_url: String,
    pub is_default: i32,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct SystemStateRow {
    pub key: String,
    pub value: String,
    pub updated_at: String,
}
