// Google Gemini API provider.

use async_trait::async_trait;
use reqwest::Client;
use serde_json::{json, Value};
use tracing::debug;

use super::provider::{LlmProvider, LlmResponse};

const GEMINI_API_BASE: &str = "https://generativelanguage.googleapis.com/v1beta/models";

pub struct GeminiProvider {
    pub api_key: String,
    pub client: Client,
}

impl GeminiProvider {
    pub fn new(api_key: String, client: Client) -> Self {
        Self { api_key, client }
    }
}

#[async_trait]
impl LlmProvider for GeminiProvider {
    async fn message(
        &self,
        model: &str,
        user_prompt: &str,
        system_prompt: &str,
        max_tokens: u32,
    ) -> anyhow::Result<LlmResponse> {
        debug!(provider = "gemini", model, "Sending request");

        let url = format!(
            "{}/{}:generateContent?key={}",
            GEMINI_API_BASE, model, self.api_key
        );

        let body = json!({
            "contents": [
                {
                    "parts": [{"text": user_prompt}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "generationConfig": {
                "maxOutputTokens": max_tokens
            }
        });

        let resp = self
            .client
            .post(&url)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await?;

        let status = resp.status();
        let resp_text = resp.text().await?;

        if !status.is_success() {
            anyhow::bail!(
                "Gemini API error ({}): {}",
                status.as_u16(),
                resp_text
            );
        }

        let data: Value = serde_json::from_str(&resp_text)?;

        let text = data["candidates"]
            .as_array()
            .and_then(|arr| arr.first())
            .and_then(|candidate| candidate["content"]["parts"].as_array())
            .and_then(|parts| parts.first())
            .and_then(|part| part["text"].as_str())
            .unwrap_or("")
            .to_string();

        let input_tokens = data["usageMetadata"]["promptTokenCount"]
            .as_u64()
            .unwrap_or(0);
        let output_tokens = data["usageMetadata"]["candidatesTokenCount"]
            .as_u64()
            .unwrap_or(0);

        debug!(input_tokens, output_tokens, "Gemini response received");

        Ok(LlmResponse {
            text,
            input_tokens,
            output_tokens,
        })
    }

    fn provider_name(&self) -> &str {
        "Gemini"
    }
}
