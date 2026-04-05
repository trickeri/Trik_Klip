// LlmProvider trait and LlmResponse.

use async_trait::async_trait;

/// Response from any LLM provider.
#[derive(Debug, Clone)]
pub struct LlmResponse {
    pub text: String,
    pub input_tokens: u64,
    pub output_tokens: u64,
}

/// Unified interface for all LLM providers.
#[async_trait]
pub trait LlmProvider: Send + Sync {
    /// Send a single user message with an optional system prompt and return the response.
    async fn message(
        &self,
        model: &str,
        user_prompt: &str,
        system_prompt: &str,
        max_tokens: u32,
    ) -> anyhow::Result<LlmResponse>;

    /// Human-readable provider name (e.g. "Anthropic", "OpenAI").
    fn provider_name(&self) -> &str;
}
