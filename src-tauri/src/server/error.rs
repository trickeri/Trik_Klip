use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

pub enum AppError {
    NotFound(String),
    Conflict(String),
    BadRequest(String),
    Internal(String),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, detail) = match &self {
            AppError::NotFound(msg) => (StatusCode::NOT_FOUND, msg.clone()),
            AppError::Conflict(msg) => (StatusCode::CONFLICT, msg.clone()),
            AppError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg.clone()),
            AppError::Internal(msg) => (StatusCode::INTERNAL_SERVER_ERROR, msg.clone()),
        };
        tracing::warn!(
            "AppError {} -> {}: {}",
            status.as_u16(),
            status.canonical_reason().unwrap_or(""),
            detail
        );
        (status, Json(json!({ "detail": detail }))).into_response()
    }
}

impl From<sqlx::Error> for AppError {
    fn from(err: sqlx::Error) -> Self {
        tracing::error!("Database error: {:?}", err);
        AppError::Internal(format!("Database error: {}", err))
    }
}

impl From<anyhow::Error> for AppError {
    fn from(err: anyhow::Error) -> Self {
        tracing::error!("Internal error: {:?}", err);
        AppError::Internal(format!("Internal error: {}", err))
    }
}
