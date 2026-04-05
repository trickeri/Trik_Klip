// OpenAI-compatible provider (serves OpenAI, Grok, Ollama).

use async_trait::async_trait;
use reqwest::Client;
use serde_json::{json, Value};
use tracing::debug;

use super::provider::{LlmProvider, LlmResponse};

/// A single provider struct that works for any OpenAI-compatible API:
/// OpenAI, Grok (x.ai), Ollama, and others.
pub struct OpenAiCompatProvider {
    pub api_key: String,
    pub base_url: String,
    pub provider_label: String,
    pub client: Client,
}

impl OpenAiCompatProvider {
    pub fn new(
        api_key: String,
        base_url: String,
        provider_label: String,
        client: Client,
    ) -> Self {
        Self {
            api_key,
            base_url,
            provider_label,
            client,
        }
    }

    /// Convenience constructor for OpenAI.
    pub fn openai(api_key: String, client: Client) -> Self {
        Self::new(
            api_key,
            "https://api.openai.com/v1".to_string(),
            "OpenAI".to_string(),
            client,
        )
    }

    /// Convenience constructor for Grok (x.ai).
    pub fn grok(api_key: String, client: Client) -> Self {
        Self::new(
            api_key,
            "https://api.x.ai/v1".to_string(),
            "Grok".to_string(),
            client,
        )
    }

    /// Convenience constructor for Ollama.
    pub fn ollama(client: Client) -> Self {
        Self::new(
            "ollama".to_string(),
            "http://localhost:11434/v1".to_string(),
            "Ollama".to_string(),
            client,
        )
    }

    /// Convenience constructor for Ollama with a custom base URL.
    pub fn ollama_with_url(base_url: String, client: Client) -> Self {
        Self::new(
            "ollama".to_string(),
            base_url,
            "Ollama".to_string(),
            client,
        )
    }
}

#[async_trait]
impl LlmProvider for OpenAiCompatProvider {
    async fn message(
        &self,
        model: &str,
        user_prompt: &str,
        system_prompt: &str,
        max_tokens: u32,
    ) -> anyhow::Result<LlmResponse> {
        debug!(provider = %self.provider_label, model, "Sending request");

        let url = format!("{}/chat/completions", self.base_url.trim_end_matches('/'));

        let body = json!({
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        });

        let resp = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await?;

        let status = resp.status();
        let resp_text = resp.text().await?;

        if !status.is_success() {
            anyhow::bail!(
                "{} API error ({}): {}",
                self.provider_label,
                status.as_u16(),
                resp_text
            );
        }

        let data: Value = serde_json::from_str(&resp_text)?;

        let text = data["choices"]
            .as_array()
            .and_then(|arr| arr.first())
            .and_then(|choice| choice["message"]["content"].as_str())
            .unwrap_or("")
            .to_string();

        let input_tokens = data["usage"]["prompt_tokens"].as_u64().unwrap_or(0);
        let output_tokens = data["usage"]["completion_tokens"].as_u64().unwrap_or(0);

        debug!(input_tokens, output_tokens, provider = %self.provider_label, "Response received");

        Ok(LlmResponse {
            text,
            input_tokens,
            output_tokens,
        })
    }

    fn provider_name(&self) -> &str {
        &self.provider_label
    }
}
