// Claude Code CLI subprocess provider.
// Lifted from MEEM Dashboard, adapted with LlmProvider trait impl.

use std::fmt;
use std::process::Command;

use async_trait::async_trait;
use reqwest::Client;
use serde_json::Value;
use tracing::{debug, warn};

use super::anthropic::AnthropicProvider;
use super::provider::{LlmProvider, LlmResponse};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

const RATE_LIMIT_PHRASES: &[&str] = &[
    "rate limit",
    "usage limit",
    "token limit",
    "too many requests",
    "quota",
    "capacity",
    "exceeded",
    "try again later",
    "billing",
];

#[derive(Debug)]
pub enum CliError {
    NotFound,
    RateLimited(String),
    ExecutionFailed(String),
    ParseError(String),
    Timeout,
}

impl fmt::Display for CliError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CliError::NotFound => write!(f, "Claude CLI not found on PATH"),
            CliError::RateLimited(msg) => write!(f, "Rate limited: {}", msg),
            CliError::ExecutionFailed(msg) => write!(f, "CLI execution failed: {}", msg),
            CliError::ParseError(msg) => write!(f, "Failed to parse CLI output: {}", msg),
            CliError::Timeout => write!(f, "Claude CLI timed out"),
        }
    }
}

impl std::error::Error for CliError {}

// ---------------------------------------------------------------------------
// CLI helpers
// ---------------------------------------------------------------------------

fn find_claude() -> Option<String> {
    for name in &["claude.cmd", "claude.exe", "claude"] {
        if let Ok(output) = Command::new("where").arg(name).output() {
            if output.status.success() {
                let path = String::from_utf8_lossy(&output.stdout);
                let first_line = path.lines().next().unwrap_or("").trim();
                if !first_line.is_empty() {
                    return Some(first_line.to_string());
                }
            }
        }
    }
    None
}

/// Check whether the Claude CLI is available on PATH.
pub fn is_available() -> bool {
    find_claude().is_some()
}

/// Call the Claude CLI as a subprocess, returning the text response.
pub async fn call_claude_cli(
    model: &str,
    system: &str,
    user_message: &str,
) -> Result<String, CliError> {
    let claude_path = find_claude().ok_or(CliError::NotFound)?;

    debug!(path = %claude_path, model, "Calling Claude CLI");

    // Prepend system prompt to user message (CLI has no separate system flag).
    let full_prompt = if system.is_empty() {
        user_message.to_string()
    } else {
        format!(
            "<system>\n{}\n</system>\n\n{}",
            system, user_message
        )
    };

    // Build command — strip ANTHROPIC_API_KEY so the CLI uses subscription auth.
    #[cfg(target_os = "windows")]
    let create_no_window = {
        #[allow(unused_imports)]
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        CREATE_NO_WINDOW
    };

    let mut cmd = Command::new(&claude_path);
    cmd.arg("-p")
        .arg(&full_prompt)
        .arg("--model")
        .arg(model)
        .arg("--output-format")
        .arg("json")
        .arg("--tools")
        .arg("")
        .env_remove("ANTHROPIC_API_KEY");

    #[cfg(target_os = "windows")]
    {
        #[allow(unused_imports)]
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(create_no_window);
    }

    let output = tokio::task::spawn_blocking(move || cmd.output())
        .await
        .map_err(|_| CliError::Timeout)?
        .map_err(|e| CliError::ExecutionFailed(e.to_string()))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    if !output.status.success() {
        let combined = format!("{}\n{}", stdout, stderr);
        let lower = combined.to_lowercase();
        for phrase in RATE_LIMIT_PHRASES {
            if lower.contains(phrase) {
                return Err(CliError::RateLimited(combined));
            }
        }
        return Err(CliError::ExecutionFailed(combined));
    }

    // Check for rate limiting in successful output too.
    let lower_stdout = stdout.to_lowercase();
    for phrase in RATE_LIMIT_PHRASES {
        if lower_stdout.contains(phrase) && stdout.len() < 500 {
            return Err(CliError::RateLimited(stdout));
        }
    }

    // Parse JSON envelope: {result: "...", is_error: false}
    let parsed: Value =
        serde_json::from_str(&stdout).map_err(|e| CliError::ParseError(e.to_string()))?;

    if parsed["is_error"].as_bool().unwrap_or(false) {
        let err_text = parsed["result"]
            .as_str()
            .unwrap_or("unknown error")
            .to_string();
        let lower = err_text.to_lowercase();
        for phrase in RATE_LIMIT_PHRASES {
            if lower.contains(phrase) {
                return Err(CliError::RateLimited(err_text));
            }
        }
        return Err(CliError::ExecutionFailed(err_text));
    }

    let result_text = parsed["result"]
        .as_str()
        .unwrap_or("")
        .to_string();

    debug!(len = result_text.len(), "Claude CLI response received");

    Ok(result_text)
}

// ---------------------------------------------------------------------------
// LlmProvider wrapper
// ---------------------------------------------------------------------------

pub struct ClaudeCliProvider {
    pub fallback_api_key: Option<String>,
    pub client: Client,
}

impl ClaudeCliProvider {
    pub fn new(fallback_api_key: Option<String>, client: Client) -> Self {
        Self {
            fallback_api_key,
            client,
        }
    }
}

#[async_trait]
impl LlmProvider for ClaudeCliProvider {
    async fn message(
        &self,
        model: &str,
        user_prompt: &str,
        system_prompt: &str,
        max_tokens: u32,
    ) -> anyhow::Result<LlmResponse> {
        match call_claude_cli(model, system_prompt, user_prompt).await {
            Ok(text) => Ok(LlmResponse {
                text,
                input_tokens: 0,
                output_tokens: 0,
            }),
            Err(CliError::RateLimited(msg)) => {
                if let Some(ref api_key) = self.fallback_api_key {
                    warn!("Claude CLI rate limited, falling back to direct Anthropic API: {}", msg);
                    let fallback = AnthropicProvider::new(api_key.clone(), self.client.clone());
                    fallback
                        .message(model, user_prompt, system_prompt, max_tokens)
                        .await
                } else {
                    Err(anyhow::anyhow!("Claude CLI rate limited: {}", msg))
                }
            }
            Err(e) => Err(anyhow::anyhow!("{}", e)),
        }
    }

    fn provider_name(&self) -> &str {
        "Claude Code"
    }
}
