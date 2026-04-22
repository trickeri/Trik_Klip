pub mod config;
pub mod error;
pub mod pipeline;
pub mod premiere;
pub mod routes;

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use axum::{Router, extract::Request, middleware, response::Response};
use tokio::sync::{broadcast, watch, RwLock};
use tower_http::cors::CorsLayer;
use tracing_subscriber::{EnvFilter, fmt, layer::SubscriberExt, util::SubscriberInitExt};
use trik_klip_core::db;
use trik_klip_core::llm::provider_registry;
use trik_klip_core::models::ProgressEvent;

pub struct AppState {
    pub db: sqlx::SqlitePool,
    pub settings: config::Settings,
    pub http_client: reqwest::Client,
    pub pipeline_running: AtomicBool,
    pub cancel_tx: watch::Sender<bool>,
    pub progress_tx: broadcast::Sender<ProgressEvent>,
    /// Cached per-provider model lists. Seeded with static defaults on startup,
    /// then refreshed in the background using env-configured API keys.
    pub provider_models: Arc<RwLock<HashMap<String, Vec<String>>>>,
}

impl AppState {
    /// Collect API keys from env first, then fall back to saved profile keys
    /// for any provider the env hasn't configured. A user who only set up keys
    /// via the Settings profile editor still gets a live refresh.
    async fn collect_api_keys(&self) -> HashMap<String, String> {
        let mut keys = HashMap::new();
        let settings = &self.settings;
        if !settings.anthropic_api_key.is_empty() {
            keys.insert("ANTHROPIC_API_KEY".into(), settings.anthropic_api_key.clone());
        }
        if !settings.openai_api_key.is_empty() {
            keys.insert("OPENAI_API_KEY".into(), settings.openai_api_key.clone());
        }
        if !settings.gemini_api_key.is_empty() {
            keys.insert("GEMINI_API_KEY".into(), settings.gemini_api_key.clone());
        }
        if !settings.xai_api_key.is_empty() {
            keys.insert("XAI_API_KEY".into(), settings.xai_api_key.clone());
        }

        // Fall back to saved profile keys for any provider still missing.
        match db::list_provider_profiles(&self.db).await {
            Ok(profiles) => {
                for profile in profiles {
                    if profile.api_key.is_empty() {
                        continue;
                    }
                    let env_name = match profile.provider.as_str() {
                        "anthropic" => "ANTHROPIC_API_KEY",
                        "openai" => "OPENAI_API_KEY",
                        "gemini" => "GEMINI_API_KEY",
                        "grok" => "XAI_API_KEY",
                        _ => continue,
                    };
                    keys.entry(env_name.to_string()).or_insert(profile.api_key);
                }
            }
            Err(e) => {
                tracing::warn!("Could not read profiles for model refresh: {}", e);
            }
        }

        keys
    }

    /// Refresh the model cache by hitting each provider's live /models endpoint
    /// (for providers where we have an API key). Providers without keys retain
    /// whatever was in the cache (usually the static defaults).
    pub async fn refresh_provider_models(self: &Arc<Self>) {
        let mut providers = provider_registry::list_providers();
        let api_keys = self.collect_api_keys().await;
        provider_registry::refresh_provider_models(
            &mut providers,
            &self.http_client,
            &api_keys,
        )
        .await;

        let mut cache = self.provider_models.write().await;
        for (key, info) in providers.iter() {
            cache.insert(key.to_string(), info.models.clone());
        }
        tracing::info!(
            "Provider model cache refreshed ({} providers, {} keys available)",
            cache.len(),
            api_keys.len()
        );
    }
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

    // Seed the model cache with the static defaults so handlers can serve
    // requests immediately, even before the first live refresh completes.
    let initial_models: HashMap<String, Vec<String>> = provider_registry::list_providers()
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.models))
        .collect();

    let state = Arc::new(AppState {
        db: pool,
        settings,
        http_client: reqwest::Client::new(),
        pipeline_running: AtomicBool::new(false),
        cancel_tx,
        progress_tx,
        provider_models: Arc::new(RwLock::new(initial_models)),
    });

    // Kick off a background refresh so /api/providers reflects live model lists
    // once providers respond. Failures per-provider are logged and keep defaults.
    {
        let state = state.clone();
        tokio::spawn(async move {
            state.refresh_provider_models().await;
        });
    }

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
