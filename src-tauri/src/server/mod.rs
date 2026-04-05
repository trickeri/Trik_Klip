pub mod config;
pub mod error;
pub mod pipeline;
pub mod routes;

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use axum::{Router, extract::Request, middleware, response::Response};
use tokio::sync::{broadcast, watch};
use tower_http::cors::CorsLayer;
use tracing_subscriber::{EnvFilter, fmt, layer::SubscriberExt, util::SubscriberInitExt};
use trik_klip_core::models::ProgressEvent;

pub struct AppState {
    pub db: sqlx::SqlitePool,
    pub settings: config::Settings,
    pub http_client: reqwest::Client,
    pub pipeline_running: AtomicBool,
    pub cancel_tx: watch::Sender<bool>,
    pub progress_tx: broadcast::Sender<ProgressEvent>,
}

/// Initialize tracing (file + stderr). Call ONCE before anything else.
/// Returns a guard that must be kept alive for the lifetime of the process.
pub fn init_tracing() -> Option<tracing_appender::non_blocking::WorkerGuard> {
    let settings = config::Settings::load_early().ok()?;
    let log_dir = std::path::PathBuf::from(&settings.data_dir).join("logs");
    std::fs::create_dir_all(&log_dir).ok()?;

    let file_appender = tracing_appender::rolling::daily(&log_dir, "trik_klip.log");
    let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);

    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .with(fmt::layer().with_writer(std::io::stderr))
        .with(fmt::layer().with_writer(non_blocking).with_ansi(false))
        .init();

    Some(guard)
}

pub async fn start_server() -> anyhow::Result<()> {
    let settings = config::Settings::load_early()?;

    tracing::info!("=== Trik Klip backend starting ===");
    let log_dir = std::path::PathBuf::from(&settings.data_dir).join("logs");
    tracing::info!("Log file: {}", log_dir.join("trik_klip.log").display());
    tracing::info!("Data dir: {}", settings.data_dir);
    tracing::info!("API port: {}", settings.api_port);
    tracing::info!(
        "API keys: anthropic={}, openai={}, gemini={}, xai={}",
        !settings.anthropic_api_key.is_empty(),
        !settings.openai_api_key.is_empty(),
        !settings.gemini_api_key.is_empty(),
        !settings.xai_api_key.is_empty(),
    );

    let db_path = std::path::PathBuf::from(&settings.data_dir).join("trik_klip.db");
    let pool = trik_klip_core::db::init_pool(&db_path.to_string_lossy()).await?;

    let port = settings.api_port;

    let (cancel_tx, _cancel_rx) = watch::channel(false);
    let (progress_tx, _) = broadcast::channel::<ProgressEvent>(256);

    let state = Arc::new(AppState {
        db: pool,
        settings,
        http_client: reqwest::Client::new(),
        pipeline_running: AtomicBool::new(false),
        cancel_tx,
        progress_tx,
    });

    let app = Router::new()
        .merge(routes::build_routes())
        .layer(middleware::from_fn(log_request))
        .layer(CorsLayer::very_permissive())
        .with_state(state);

    let addr = format!("127.0.0.1:{}", port);
    tracing::info!("Backend server listening on {}", addr);
    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) => {
            tracing::error!("FATAL: Cannot bind to {} — {}", addr, e);
            tracing::error!("Another process may be using port {}. Kill it and restart.", port);
            return Err(e.into());
        }
    };
    tracing::info!("Server ready, accepting connections");
    axum::serve(listener, app).await?;
    Ok(())
}

async fn log_request(req: Request, next: middleware::Next) -> Response {
    let method = req.method().clone();
    let uri = req.uri().clone();
    let start = std::time::Instant::now();

    tracing::info!("--> {} {}", method, uri);

    let response = next.run(req).await;

    let duration = start.elapsed();
    let status = response.status();
    tracing::info!(
        "<-- {} {} -> {} ({:.3}s)",
        method, uri, status.as_u16(), duration.as_secs_f64()
    );

    response
}
