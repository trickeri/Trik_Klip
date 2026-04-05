// Anthropic Claude API provider (direct HTTP).

use async_trait::async_trait;
use reqwest::Client;
use serde_json::{json, Value};
use tracing::debug;

use super::provider::{LlmProvider, LlmResponse};

const ANTHROPIC_API_URL: &str = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION: &str = "2023-06-01";

pub struct AnthropicProvider {
    pub api_key: String,
    pub client: Client,
}

impl AnthropicProvider {
    pub fn new(api_key: String, client: Client) -> Self {
        Self { api_key, client }
    }
}

#[async_trait]
impl LlmProvider for AnthropicProvider {
    async fn message(
        &self,
        model: &str,
        user_prompt: &str,
        system_prompt: &str,
        max_tokens: u32,
    ) -> anyhow::Result<LlmResponse> {
        debug!(provider = "anthropic", model, "Sending request");

        let body = json!({
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "system": system_prompt,
        });

        let resp = self
            .client
            .post(ANTHROPIC_API_URL)
            .header("x-api-key", &self.api_key)
            .header("anthropic-version", ANTHROPIC_VERSION)
            .header("content-type", "application/json")
            .json(&body)
            .send()
            .await?;

        let status = resp.status();
        let resp_text = resp.text().await?;

        if !status.is_success() {
            anyhow::bail!(
                "Anthropic API error ({}): {}",
                status.as_u16(),
                resp_text
            );
        }

        let data: Value = serde_json::from_str(&resp_text)?;

        let text = data["content"]
            .as_array()
            .and_then(|arr| arr.first())
            .and_then(|block| block["text"].as_str())
            .unwrap_or("")
            .to_string();

        let input_tokens = data["usage"]["input_tokens"].as_u64().unwrap_or(0);
        let output_tokens = data["usage"]["output_tokens"].as_u64().unwrap_or(0);

        debug!(input_tokens, output_tokens, "Anthropic response received");

        Ok(LlmResponse {
            text,
            input_tokens,
            output_tokens,
        })
    }

    fn provider_name(&self) -> &str {
        "Anthropic"
    }
}
