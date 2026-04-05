// Provider registry — model lists, live refresh, factory.

use std::collections::HashMap;

use reqwest::Client;
use serde_json::Value;
use tracing::{debug, warn};

use super::anthropic::AnthropicProvider;
use super::claude_cli::ClaudeCliProvider;
use super::gemini::GeminiProvider;
use super::openai_compat::OpenAiCompatProvider;
use super::provider::LlmProvider;

// ---------------------------------------------------------------------------
// ProviderInfo
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct ProviderInfo {
    pub label: &'static str,
    pub env_key: &'static str,
    pub default_model: &'static str,
    pub models: Vec<String>,
    pub base_url: &'static str,
}

// ---------------------------------------------------------------------------
// Static default model lists
// ---------------------------------------------------------------------------

fn default_anthropic_models() -> Vec<String> {
    [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

fn default_openai_models() -> Vec<String> {
    [
        "o3",
        "o4-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

fn default_gemini_models() -> Vec<String> {
    [
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

fn default_grok_models() -> Vec<String> {
    [
        "grok-3",
        "grok-3-fast",
        "grok-3-mini",
        "grok-3-mini-fast",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

fn default_ollama_models() -> Vec<String> {
    [
        "qwen3.5:27b",
        "qwen3:14b",
        "llama3.1:8b",
        "gemma3:12b",
        "mistral:7b",
        "deepseek-r1:14b",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

fn default_claude_code_models() -> Vec<String> {
    [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

// ---------------------------------------------------------------------------
// Registry construction
// ---------------------------------------------------------------------------

/// Build the full providers map with default model lists.
pub fn list_providers() -> HashMap<&'static str, ProviderInfo> {
    let mut map = HashMap::new();

    map.insert(
        "anthropic",
        ProviderInfo {
            label: "Anthropic",
            env_key: "ANTHROPIC_API_KEY",
            default_model: "claude-sonnet-4-6",
            models: default_anthropic_models(),
            base_url: "https://api.anthropic.com",
        },
    );

    map.insert(
        "openai",
        ProviderInfo {
            label: "OpenAI",
            env_key: "OPENAI_API_KEY",
            default_model: "gpt-4.1",
            models: default_openai_models(),
            base_url: "https://api.openai.com/v1",
        },
    );

    map.insert(
        "gemini",
        ProviderInfo {
            label: "Google Gemini",
            env_key: "GEMINI_API_KEY",
            default_model: "gemini-2.5-flash-preview-05-20",
            models: default_gemini_models(),
            base_url: "https://generativelanguage.googleapis.com",
        },
    );

    map.insert(
        "grok",
        ProviderInfo {
            label: "Grok",
            env_key: "XAI_API_KEY",
            default_model: "grok-3-fast",
            models: default_grok_models(),
            base_url: "https://api.x.ai/v1",
        },
    );

    map.insert(
        "ollama",
        ProviderInfo {
            label: "Ollama",
            env_key: "",
            default_model: "qwen3:14b",
            models: default_ollama_models(),
            base_url: "http://localhost:11434/v1",
        },
    );

    map.insert(
        "claude_code",
        ProviderInfo {
            label: "Claude Code",
            env_key: "",
            default_model: "claude-sonnet-4-6",
            models: default_claude_code_models(),
            base_url: "",
        },
    );

    map
}

// ---------------------------------------------------------------------------
// Live model fetchers
// ---------------------------------------------------------------------------

/// Fetch available models from the Anthropic API.
pub async fn fetch_anthropic_models(
    client: &Client,
    api_key: &str,
) -> anyhow::Result<Vec<String>> {
    debug!("Fetching Anthropic models");

    let resp = client
        .get("https://api.anthropic.com/v1/models")
        .header("x-api-key", api_key)
        .header("anthropic-version", "2023-06-01")
        .send()
        .await?;

    if !resp.status().is_success() {
        anyhow::bail!("Anthropic models API returned {}", resp.status());
    }

    let data: Value = resp.json().await?;
    let mut models: Vec<String> = data["data"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|m| m["id"].as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();

    models.sort();
    Ok(models)
}

/// Fetch available models from an OpenAI-compatible API.
pub async fn fetch_openai_models(
    client: &Client,
    api_key: &str,
) -> anyhow::Result<Vec<String>> {
    fetch_openai_compat_models(client, api_key, "https://api.openai.com/v1").await
}

/// Fetch available models from the Grok (x.ai) API.
pub async fn fetch_grok_models(
    client: &Client,
    api_key: &str,
) -> anyhow::Result<Vec<String>> {
    fetch_openai_compat_models(client, api_key, "https://api.x.ai/v1").await
}

async fn fetch_openai_compat_models(
    client: &Client,
    api_key: &str,
    base_url: &str,
) -> anyhow::Result<Vec<String>> {
    debug!(base_url, "Fetching OpenAI-compatible models");

    let url = format!("{}/models", base_url.trim_end_matches('/'));

    let resp = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", api_key))
        .send()
        .await?;

    if !resp.status().is_success() {
        anyhow::bail!("Models API at {} returned {}", base_url, resp.status());
    }

    let data: Value = resp.json().await?;
    let mut models: Vec<String> = data["data"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|m| m["id"].as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();

    models.sort();
    Ok(models)
}

/// Fetch available models from the Gemini API.
pub async fn fetch_gemini_models(
    client: &Client,
    api_key: &str,
) -> anyhow::Result<Vec<String>> {
    debug!("Fetching Gemini models");

    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models?key={}",
        api_key
    );

    let resp = client.get(&url).send().await?;

    if !resp.status().is_success() {
        anyhow::bail!("Gemini models API returned {}", resp.status());
    }

    let data: Value = resp.json().await?;
    let mut models: Vec<String> = data["models"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|m| {
                    m["name"]
                        .as_str()
                        .map(|name| name.trim_start_matches("models/").to_string())
                })
                .collect()
        })
        .unwrap_or_default();

    models.sort();
    Ok(models)
}

/// List models available from a local Ollama instance.
pub async fn list_ollama_models(
    client: &Client,
    base_url: &str,
) -> anyhow::Result<Vec<String>> {
    debug!(base_url, "Listing Ollama models");

    // Ollama's native API endpoint for listing models.
    let native_url = base_url
        .trim_end_matches('/')
        .trim_end_matches("/v1")
        .to_string();
    let url = format!("{}/api/tags", native_url);

    let resp = client.get(&url).send().await?;

    if !resp.status().is_success() {
        anyhow::bail!("Ollama tags API returned {}", resp.status());
    }

    let data: Value = resp.json().await?;
    let mut models: Vec<String> = data["models"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|m| m["name"].as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();

    models.sort();
    Ok(models)
}

// ---------------------------------------------------------------------------
// Refresh all provider models in-place
// ---------------------------------------------------------------------------

/// Attempt to refresh each provider's model list from live APIs.
/// Providers whose API keys are missing or whose requests fail keep their defaults.
pub async fn refresh_provider_models(
    providers: &mut HashMap<&'static str, ProviderInfo>,
    client: &Client,
    api_keys: &HashMap<String, String>,
) {
    // Anthropic
    if let Some(key) = api_keys.get("ANTHROPIC_API_KEY") {
        match fetch_anthropic_models(client, key).await {
            Ok(models) if !models.is_empty() => {
                if let Some(p) = providers.get_mut("anthropic") {
                    p.models = models;
                }
            }
            Err(e) => warn!("Failed to refresh Anthropic models: {}", e),
            _ => {}
        }
    }

    // OpenAI
    if let Some(key) = api_keys.get("OPENAI_API_KEY") {
        match fetch_openai_models(client, key).await {
            Ok(models) if !models.is_empty() => {
                if let Some(p) = providers.get_mut("openai") {
                    p.models = models;
                }
            }
            Err(e) => warn!("Failed to refresh OpenAI models: {}", e),
            _ => {}
        }
    }

    // Gemini
    if let Some(key) = api_keys.get("GEMINI_API_KEY") {
        match fetch_gemini_models(client, key).await {
            Ok(models) if !models.is_empty() => {
                if let Some(p) = providers.get_mut("gemini") {
                    p.models = models;
                }
            }
            Err(e) => warn!("Failed to refresh Gemini models: {}", e),
            _ => {}
        }
    }

    // Grok
    if let Some(key) = api_keys.get("XAI_API_KEY") {
        match fetch_grok_models(client, key).await {
            Ok(models) if !models.is_empty() => {
                if let Some(p) = providers.get_mut("grok") {
                    p.models = models;
                }
            }
            Err(e) => warn!("Failed to refresh Grok models: {}", e),
            _ => {}
        }
    }

    // Ollama — no API key needed, just try to reach the server.
    if let Some(p) = providers.get("ollama") {
        let base = p.base_url.to_string();
        match list_ollama_models(client, &base).await {
            Ok(models) if !models.is_empty() => {
                if let Some(p) = providers.get_mut("ollama") {
                    p.models = models;
                }
            }
            Err(e) => debug!("Ollama not reachable, keeping defaults: {}", e),
            _ => {}
        }
    }
}

// ---------------------------------------------------------------------------
// Provider factory
// ---------------------------------------------------------------------------

/// Construct a boxed `LlmProvider` for the given provider key.
pub fn make_provider(
    provider: &str,
    api_key: &str,
    base_url: &str,
    client: Client,
) -> anyhow::Result<Box<dyn LlmProvider>> {
    match provider {
        "anthropic" => Ok(Box::new(AnthropicProvider::new(
            api_key.to_string(),
            client,
        ))),

        "openai" => Ok(Box::new(OpenAiCompatProvider::new(
            api_key.to_string(),
            if base_url.is_empty() {
                "https://api.openai.com/v1".to_string()
            } else {
                base_url.to_string()
            },
            "OpenAI".to_string(),
            client,
        ))),

        "grok" => Ok(Box::new(OpenAiCompatProvider::new(
            api_key.to_string(),
            if base_url.is_empty() {
                "https://api.x.ai/v1".to_string()
            } else {
                base_url.to_string()
            },
            "Grok".to_string(),
            client,
        ))),

        "ollama" => Ok(Box::new(OpenAiCompatProvider::new(
            "ollama".to_string(),
            if base_url.is_empty() {
                "http://localhost:11434/v1".to_string()
            } else {
                base_url.to_string()
            },
            "Ollama".to_string(),
            client,
        ))),

        "gemini" => Ok(Box::new(GeminiProvider::new(
            api_key.to_string(),
            client,
        ))),

        "claude_code" => {
            let fallback = if api_key.is_empty() {
                None
            } else {
                Some(api_key.to_string())
            };
            Ok(Box::new(ClaudeCliProvider::new(fallback, client)))
        }

        other => anyhow::bail!("Unknown provider: {}", other),
    }
}
