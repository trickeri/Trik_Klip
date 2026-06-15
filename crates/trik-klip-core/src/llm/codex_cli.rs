// OpenAI Codex CLI subprocess provider.
// Mirrors claude_cli.rs: shells out to the `codex` CLI in non-interactive
// `exec` mode and uses the user's ChatGPT subscription auth (Plus/Pro) rather
// than an OpenAI API key. The API key, if configured, is only used as a
// rate-limit fallback.

use std::fmt;
use std::process::Stdio;

use async_trait::async_trait;
use reqwest::Client;
use serde_json::Value;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tracing::{debug, warn};

use super::openai_compat::OpenAiCompatProvider;
use super::provider::{LlmProvider, LlmResponse};
use crate::cancel::{wait_cancelled, CancelRx};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

// Codex prints these (and close variants) when a ChatGPT subscription has
// exhausted its Codex usage/credit allowance. Matched case-insensitively as
// substrings so window-specific suffixes ("for the next 5 hours", URLs, etc.)
// still trip them. See openai/codex CLI strings.
const RATE_LIMIT_PHRASES: &[&str] = &[
    "hit your usage limit",
    "usage limit reached",
    "reached your usage limit",
    "out of credits",
    "credit limit",
    "rate limit reached",
    "rate limit",
    "too many requests",
    "quota",
    "try again later",
];

#[derive(Debug)]
pub enum CodexError {
    NotFound,
    RateLimited(String),
    ExecutionFailed(String),
    ParseError(String),
    Timeout,
}

impl fmt::Display for CodexError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CodexError::NotFound => write!(f, "Codex CLI not found on PATH"),
            CodexError::RateLimited(msg) => write!(f, "Rate limited: {}", msg),
            CodexError::ExecutionFailed(msg) => write!(f, "CLI execution failed: {}", msg),
            CodexError::ParseError(msg) => write!(f, "Failed to parse CLI output: {}", msg),
            CodexError::Timeout => write!(f, "Codex CLI timed out"),
        }
    }
}

impl std::error::Error for CodexError {}

// ---------------------------------------------------------------------------
// CLI helpers
// ---------------------------------------------------------------------------

#[cfg(target_os = "windows")]
fn which(name: &str) -> Option<String> {
    let mut cmd = std::process::Command::new("where");
    cmd.arg(name);
    // Suppress the per-invocation console flash on Windows (same reason as the
    // Claude CLI provider — this runs per chunk per worker during analysis).
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

// Unix has no `where` command — scan PATH directly for an executable file.
// See claude_cli::which for rationale.
#[cfg(not(target_os = "windows"))]
fn which(name: &str) -> Option<String> {
    use std::os::unix::fs::PermissionsExt;
    let path_var = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_var) {
        let candidate = dir.join(name);
        if let Ok(meta) = std::fs::metadata(&candidate) {
            if meta.is_file() && meta.permissions().mode() & 0o111 != 0 {
                return Some(candidate.to_string_lossy().into_owned());
            }
        }
    }
    None
}

/// Resolve the native `codex.exe` that npm's `.cmd` shim ultimately launches.
///
/// npm installs Codex as a thin `codex.cmd` → `node codex.js` launcher that
/// then execs a platform-specific native binary nested under:
///   <npm_prefix>/node_modules/@openai/codex/node_modules/@openai/codex-win32-<arch>/vendor/<triple>/codex/codex.exe
/// (or hoisted one level up). Calling the `.exe` directly sidesteps both the
/// Node hop and Rust's `.cmd` BatBadBut mitigation.
#[cfg(target_os = "windows")]
fn resolve_native_codex_exe(cmd_path: &str) -> Option<String> {
    let dir = std::path::Path::new(cmd_path).parent()?;

    let (arch_pkg, triple) = if cfg!(target_arch = "aarch64") {
        ("codex-win32-arm64", "aarch64-pc-windows-msvc")
    } else {
        ("codex-win32-x64", "x86_64-pc-windows-msvc")
    };

    let tail = std::path::Path::new("vendor")
        .join(triple)
        .join("codex")
        .join("codex.exe");

    // Hoisted layout: node_modules/@openai/codex-win32-<arch>/...
    let hoisted = dir
        .join("node_modules")
        .join("@openai")
        .join(arch_pkg)
        .join(&tail);
    if hoisted.exists() {
        return Some(hoisted.to_string_lossy().into_owned());
    }

    // Nested layout: node_modules/@openai/codex/node_modules/@openai/codex-win32-<arch>/...
    let nested = dir
        .join("node_modules")
        .join("@openai")
        .join("codex")
        .join("node_modules")
        .join("@openai")
        .join(arch_pkg)
        .join(&tail);
    if nested.exists() {
        return Some(nested.to_string_lossy().into_owned());
    }

    None
}

fn find_codex_uncached() -> Option<String> {
    // Prefer a native exe already on PATH (Homebrew / standalone installs).
    if let Some(p) = which("codex.exe") {
        return Some(p);
    }

    // npm install: locate the .cmd shim and resolve to the native exe when we
    // can; otherwise fall back to the shim itself (our argv is all clean flags,
    // so the BatBadBut mitigation won't trip — the prompt goes via stdin).
    if let Some(cmd_path) = which("codex.cmd") {
        #[cfg(target_os = "windows")]
        if let Some(native) = resolve_native_codex_exe(&cmd_path) {
            return Some(native);
        }
        return Some(cmd_path);
    }

    // Unix-style name on PATH.
    which("codex")
}

/// Cached codex path resolution (see claude_cli::find_claude for rationale —
/// avoids spawning `where.exe` per LLM call).
fn find_codex() -> Option<String> {
    static CACHE: std::sync::OnceLock<Option<String>> = std::sync::OnceLock::new();
    CACHE.get_or_init(find_codex_uncached).clone()
}

/// Check whether the Codex CLI is available on PATH.
pub fn is_available() -> bool {
    find_codex().is_some()
}

/// Extract the final assistant message from Codex's `--json` JSONL stream.
///
/// Each line is a JSON event. The answer is the `item.text` of the last
/// `{"type":"item.completed","item":{"type":"agent_message",...}}`. A
/// `turn.failed`/`error` event carries the failure message instead.
fn parse_codex_jsonl(stdout: &str) -> Result<String, CodexError> {
    let mut last_message: Option<String> = None;
    let mut failure: Option<String> = None;

    for line in stdout.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Ok(event) = serde_json::from_str::<Value>(line) else {
            continue; // ignore non-JSON noise
        };

        match event["type"].as_str() {
            Some("item.completed") => {
                let item = &event["item"];
                if item["type"].as_str() == Some("agent_message") {
                    if let Some(text) = item["text"].as_str() {
                        last_message = Some(text.to_string());
                    }
                }
            }
            Some("turn.failed") => {
                failure = Some(
                    event["error"]["message"]
                        .as_str()
                        .or_else(|| event["message"].as_str())
                        .unwrap_or("Codex turn failed")
                        .to_string(),
                );
            }
            Some("error") => {
                failure = Some(
                    event["message"]
                        .as_str()
                        .unwrap_or("Codex error")
                        .to_string(),
                );
            }
            _ => {}
        }
    }

    if let Some(text) = last_message {
        return Ok(text);
    }
    if let Some(msg) = failure {
        let lower = msg.to_lowercase();
        for phrase in RATE_LIMIT_PHRASES {
            if lower.contains(phrase) {
                return Err(CodexError::RateLimited(msg));
            }
        }
        return Err(CodexError::ExecutionFailed(msg));
    }
    Err(CodexError::ParseError(
        "no agent_message found in Codex output".to_string(),
    ))
}

/// Call the Codex CLI as a subprocess, returning the text response.
pub async fn call_codex_cli(
    model: &str,
    system: &str,
    user_message: &str,
    mut cancel_rx: Option<CancelRx>,
) -> Result<String, CodexError> {
    let codex_path = find_codex().ok_or(CodexError::NotFound)?;

    debug!(path = %codex_path, model, "Calling Codex CLI");

    // Prepend system prompt to user message (exec has no separate system flag).
    let full_prompt = if system.is_empty() {
        user_message.to_string()
    } else {
        format!("<system>\n{}\n</system>\n\n{}", system, user_message)
    };

    #[cfg(target_os = "windows")]
    let create_no_window = {
        #[allow(unused_imports)]
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        CREATE_NO_WINDOW
    };

    // Non-interactive, read-only, never-prompt, JSONL output. Prompt arrives via
    // stdin (omit the positional arg → Codex reads stdin as the prompt), which
    // keeps argv free of newlines/quotes for the Windows .cmd path.
    let mut cmd = Command::new(&codex_path);
    cmd.arg("exec")
        .arg("--json")
        .arg("-s")
        .arg("read-only")
        .arg("--skip-git-repo-check")
        // Force ChatGPT subscription auth even if a stray API key lingers.
        .arg("-c")
        .arg("forced_login_method=chatgpt");
    // Only pin a model when one is requested; otherwise let the user's
    // ~/.codex/config.toml / account default decide (model names drift between
    // CLI versions, and an invalid -m errors out).
    if !model.is_empty() {
        cmd.arg("-m").arg(model);
    }
    cmd.env_remove("OPENAI_API_KEY")
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
        .map_err(|e| CodexError::ExecutionFailed(e.to_string()))?;

    // Write the prompt to stdin, then drop it so Codex sees EOF (an open empty
    // stdin pipe makes `codex exec` hang waiting for input).
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(full_prompt.as_bytes())
            .await
            .map_err(|e| CodexError::ExecutionFailed(format!("stdin write: {}", e)))?;
        // dropping stdin closes it; happens at end of scope
    }

    // Drain stdout/stderr concurrently so a full pipe can't deadlock the child.
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

    // 5-minute hard ceiling per call (matches the Claude CLI provider).
    const CODEX_CLI_TIMEOUT_SECS: u64 = 300;

    let status = tokio::select! {
        s = child.wait() => s.map_err(|e| CodexError::ExecutionFailed(e.to_string()))?,
        _ = wait_cancelled(cancel_rx.as_mut()) => {
            let _ = child.kill().await;
            return Err(CodexError::ExecutionFailed("Pipeline cancelled by user".into()));
        }
        _ = tokio::time::sleep(std::time::Duration::from_secs(CODEX_CLI_TIMEOUT_SECS)) => {
            warn!("Codex CLI call exceeded {}s — killing", CODEX_CLI_TIMEOUT_SECS);
            let _ = child.kill().await;
            return Err(CodexError::Timeout);
        }
    };

    let stdout_bytes = stdout_handle.await.unwrap_or_default();
    let stderr_bytes = stderr_handle.await.unwrap_or_default();

    let stdout = String::from_utf8_lossy(&stdout_bytes).to_string();
    let stderr = String::from_utf8_lossy(&stderr_bytes).to_string();

    if !status.success() {
        let combined = format!("{}\n{}", stdout, stderr);
        let lower = combined.to_lowercase();
        for phrase in RATE_LIMIT_PHRASES {
            if lower.contains(phrase) {
                return Err(CodexError::RateLimited(combined));
            }
        }
        return Err(CodexError::ExecutionFailed(combined));
    }

    // Usage limits can also surface on a zero exit with the phrase on stderr.
    let lower_combined = format!("{}\n{}", stdout, stderr).to_lowercase();
    for phrase in RATE_LIMIT_PHRASES {
        if lower_combined.contains(phrase) {
            return Err(CodexError::RateLimited(stderr.clone()));
        }
    }

    let result_text = parse_codex_jsonl(&stdout)?;

    debug!(len = result_text.len(), "Codex CLI response received");

    Ok(result_text)
}

// ---------------------------------------------------------------------------
// LlmProvider wrapper
// ---------------------------------------------------------------------------

pub struct CodexCliProvider {
    pub fallback_api_key: Option<String>,
    pub client: Client,
    pub cancel_rx: Option<CancelRx>,
}

impl CodexCliProvider {
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
impl LlmProvider for CodexCliProvider {
    async fn message(
        &self,
        model: &str,
        user_prompt: &str,
        system_prompt: &str,
        max_tokens: u32,
    ) -> anyhow::Result<LlmResponse> {
        match call_codex_cli(model, system_prompt, user_prompt, self.cancel_rx.clone()).await {
            Ok(text) => Ok(LlmResponse {
                text,
                input_tokens: 0,
                output_tokens: 0,
            }),
            Err(CodexError::RateLimited(msg)) => {
                if let Some(ref api_key) = self.fallback_api_key {
                    warn!("Codex CLI rate limited, falling back to OpenAI API: {}", msg);
                    let fallback = OpenAiCompatProvider::openai(api_key.clone(), self.client.clone());
                    fallback
                        .message(model, user_prompt, system_prompt, max_tokens)
                        .await
                } else {
                    Err(anyhow::anyhow!("Codex CLI rate limited: {}", msg))
                }
            }
            Err(e) => Err(anyhow::anyhow!("{}", e)),
        }
    }

    fn provider_name(&self) -> &str {
        "Codex CLI"
    }
}
