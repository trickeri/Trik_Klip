// Claude Code CLI subprocess provider.
// Lifted from MEEM Dashboard, adapted with LlmProvider trait impl.

use std::fmt;
use std::process::Stdio;

use async_trait::async_trait;
use reqwest::Client;
use serde_json::Value;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tracing::{debug, warn};

use super::anthropic::AnthropicProvider;
use super::provider::{LlmProvider, LlmResponse};
use crate::cancel::{wait_cancelled, CancelRx};

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

fn which(name: &str) -> Option<String> {
    let mut cmd = std::process::Command::new("where");
    cmd.arg(name);
    // Without CREATE_NO_WINDOW, each `where.exe` invocation flashes a console
    // window that steals focus — and analysis spawns this per chunk per
    // worker. Suppress the window.
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let output = cmd.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let path = String::from_utf8_lossy(&output.stdout);
    let first = path.lines().next().unwrap_or("").trim();
    if first.is_empty() {
        None
    } else {
        Some(first.to_string())
    }
}

fn find_claude_uncached() -> Option<String> {
    // Prefer claude.exe if it's on PATH (rare — usually npm only installs .cmd).
    if let Some(p) = which("claude.exe") {
        return Some(p);
    }

    // Otherwise locate the .cmd shim and resolve it to the underlying claude.exe.
    // npm's global install layout is:
    //   <npm_prefix>/claude.cmd
    //   <npm_prefix>/node_modules/@anthropic-ai/claude-code/bin/claude.exe
    // Calling the .exe directly sidesteps Rust's BatBadBut mitigation for .cmd.
    if let Some(cmd_path) = which("claude.cmd") {
        if let Some(dir) = std::path::Path::new(&cmd_path).parent() {
            let real = dir
                .join("node_modules")
                .join("@anthropic-ai")
                .join("claude-code")
                .join("bin")
                .join("claude.exe");
            if real.exists() {
                return Some(real.to_string_lossy().into_owned());
            }
        }
        // Fall back to the .cmd shim (may still trip BatBadBut for some args).
        return Some(cmd_path);
    }

    // Last-resort unix-style name.
    which("claude")
}

/// Cached claude path resolution. Without this we spawned `where.exe` per
/// LLM call — a few hundred subprocess spawns per analysis, each a flashing
/// console window on Windows. Cache is `None` if the CLI genuinely isn't
/// installed; caller will surface `CliError::NotFound`.
fn find_claude() -> Option<String> {
    static CACHE: std::sync::OnceLock<Option<String>> = std::sync::OnceLock::new();
    CACHE.get_or_init(find_claude_uncached).clone()
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
    mut cancel_rx: Option<CancelRx>,
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

    // Pass the prompt via stdin, NOT as an argv argument. On Windows, Rust's
    // CVE-2024-24576 mitigation refuses to spawn .cmd/.bat files with args
    // containing newlines, quotes, %, etc. — which every prompt has. This
    // mirrors the Python reference impl (providers.py:440 `input=...`).
    let mut cmd = Command::new(&claude_path);
    cmd.arg("-p")
        .arg("--model")
        .arg(model)
        .arg("--output-format")
        .arg("json")
        .arg("--tools")
        .arg("")
        .env_remove("ANTHROPIC_API_KEY")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        #[allow(unused_imports)]
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(create_no_window);
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| CliError::ExecutionFailed(e.to_string()))?;

    // Write the prompt to stdin, then drop it so the CLI sees EOF.
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(full_prompt.as_bytes())
            .await
            .map_err(|e| CliError::ExecutionFailed(format!("stdin write: {}", e)))?;
        // dropping stdin closes it; happens at end of scope
    }

    // Spawn background readers for stdout/stderr so the child doesn't block
    // on a full pipe while we're waiting.
    let stdout_pipe = child.stdout.take();
    let stderr_pipe = child.stderr.take();
    let stdout_handle = tokio::spawn(async move {
        use tokio::io::AsyncReadExt;
        let mut buf = Vec::new();
        if let Some(mut s) = stdout_pipe {
            let _ = s.read_to_end(&mut buf).await;
        }
        buf
    });
    let stderr_handle = tokio::spawn(async move {
        use tokio::io::AsyncReadExt;
        let mut buf = Vec::new();
        if let Some(mut s) = stderr_pipe {
            let _ = s.read_to_end(&mut buf).await;
        }
        buf
    });

    let status = tokio::select! {
        s = child.wait() => s.map_err(|e| CliError::ExecutionFailed(e.to_string()))?,
        _ = wait_cancelled(cancel_rx.as_mut()) => {
            let _ = child.kill().await;
            return Err(CliError::ExecutionFailed("Pipeline cancelled by user".into()));
        }
    };

    let stdout_bytes = stdout_handle.await.unwrap_or_default();
    let stderr_bytes = stderr_handle.await.unwrap_or_default();
    let output = std::process::Output {
        status,
        stdout: stdout_bytes,
        stderr: stderr_bytes,
    };

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
    pub cancel_rx: Option<CancelRx>,
}

impl ClaudeCliProvider {
    pub fn new(fallback_api_key: Option<String>, client: Client) -> Self {
        Self {
            fallback_api_key,
            client,
            cancel_rx: None,
        }
    }

    pub fn with_cancel(mut self, cancel_rx: CancelRx) -> Self {
        self.cancel_rx = Some(cancel_rx);
        self
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
        match call_claude_cli(model, system_prompt, user_prompt, self.cancel_rx.clone()).await {
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
