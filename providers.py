"""
Multi-provider LLM abstraction for StreamClipper.

Supports: Anthropic (Claude), OpenAI, Google Gemini, xAI (Grok), Ollama (Local).
Each provider normalises its response to a simple string return.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import urllib.request
import urllib.error

# Hide console windows spawned by subprocess on Windows (PyInstaller --windowed)
_SUBPROCESS_FLAGS = (
    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
)


# ── Provider registry ─────────────────────────────────────────────────────────

PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "env_key": "ANTHROPIC_API_KEY",
        "models": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
        ],
        "default_model": "claude-opus-4-6",
    },
    "openai": {
        "label": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "models": [
            "o3",
            "o4-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
        ],
        "default_model": "gpt-4.1",
    },
    "gemini": {
        "label": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "models": [
            "gemini-2.5-pro-preview-06-05",
            "gemini-2.5-flash-preview-05-20",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ],
        "default_model": "gemini-2.5-flash-preview-05-20",
    },
    "grok": {
        "label": "xAI (Grok)",
        "env_key": "XAI_API_KEY",
        "models": [
            "grok-3",
            "grok-3-fast",
            "grok-3-mini",
            "grok-3-mini-fast",
        ],
        "default_model": "grok-3",
    },
    "ollama": {
        "label": "Ollama (Local)",
        "env_key": "",                          # no API key needed
        "base_url": "http://localhost:11434",    # Ollama server root
        "models": [                              # popular suggestions
            "qwen3.5:27b",
            "qwen3:14b",
            "llama3.1:8b",
            "gemma3:12b",
            "mistral:7b",
            "deepseek-r1:14b",
        ],
        "default_model": "qwen3.5:27b",
    },
    "claude_code": {
        "label": "Claude Code (Subscription)",
        "env_key": "",                          # uses CLI auth, no API key needed
        "models": [
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-haiku-4-5-20251001",
        ],
        "default_model": "claude-sonnet-4-6",
    },
}


# ── Ollama helpers ────────────────────────────────────────────────────────────

def list_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Query a running Ollama server for installed model names.

    Returns a sorted list of model name strings (e.g. ["llama3.1:8b", ...]).
    Raises on connection failure so the caller can show a user-friendly error.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    models = [m["name"] for m in data.get("models", [])]
    models.sort()
    return models


# ── Live model fetchers ──────────────────────────────────────────────────────

def _fetch_json(url: str, headers: dict | None = None, timeout: int = 8) -> dict:
    """GET *url* and return parsed JSON.  Raises on any failure."""
    req = urllib.request.Request(url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _fetch_anthropic_models(api_key: str) -> list[str]:
    data = _fetch_json(
        "https://api.anthropic.com/v1/models?limit=100",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    models = [m["id"] for m in data.get("data", [])]
    # Only keep claude chat models, skip embedding / legacy
    models = [m for m in models if m.startswith("claude-")]
    models.sort(reverse=True)
    return models


def _fetch_openai_models(api_key: str) -> list[str]:
    data = _fetch_json(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    models = [m["id"] for m in data.get("data", [])]
    # Keep only chat-relevant models
    prefixes = ("gpt-4", "gpt-3.5", "o1", "o3", "o4", "chatgpt-")
    models = [m for m in models if any(m.startswith(p) for p in prefixes)]
    # Filter out internal / fine-tune variants
    models = [m for m in models if "instruct" not in m
              and ":ft-" not in m and "-realtime" not in m
              and "-audio" not in m and "-search" not in m]
    models.sort(reverse=True)
    return models


def _fetch_gemini_models(api_key: str) -> list[str]:
    data = _fetch_json(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
    )
    models = []
    for m in data.get("models", []):
        mid = m.get("name", "")
        if mid.startswith("models/"):
            mid = mid[7:]
        # Keep only generateContent-capable Gemini models
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods and mid.startswith("gemini-"):
            models.append(mid)
    models.sort(reverse=True)
    return models


def _fetch_grok_models(api_key: str) -> list[str]:
    data = _fetch_json(
        "https://api.x.ai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    models = [m["id"] for m in data.get("data", [])]
    models = [m for m in models if m.startswith("grok-")]
    models.sort(reverse=True)
    return models


_FETCHERS: dict[str, callable] = {
    "anthropic": _fetch_anthropic_models,
    "openai":    _fetch_openai_models,
    "gemini":    _fetch_gemini_models,
    "grok":      _fetch_grok_models,
    # ollama handled separately via list_ollama_models()
}


def refresh_provider_models(provider: str, api_key: str) -> list[str] | None:
    """Fetch live model list for *provider*.  Returns None on failure.

    On success the PROVIDERS dict is also updated in-place so all
    downstream code sees the fresh list.
    """
    fetcher = _FETCHERS.get(provider)
    if fetcher is None:
        return None
    try:
        models = fetcher(api_key)
    except Exception:
        return None
    if models:
        PROVIDERS[provider]["models"] = models
    return models or None


def refresh_all_models(profiles: dict[str, dict] | None = None):
    """Best-effort refresh of every provider we have a key for.

    *profiles* is the saved-profiles dict ``{name: {provider, api_key, ...}}``.
    We also check environment variables as a fallback.
    Runs synchronously but is fast (parallel would add complexity for
    a ~1-2 s total startup cost).
    """
    # Collect one API key per provider from profiles + env
    keys: dict[str, str] = {}
    if profiles:
        for p in profiles.values():
            prov = p.get("provider", "")
            key = p.get("api_key", "")
            if prov and key and prov not in keys:
                keys[prov] = key
    # Env fallback
    for prov, info in PROVIDERS.items():
        if prov not in keys and info.get("env_key"):
            env_val = os.environ.get(info["env_key"], "")
            if env_val:
                keys[prov] = env_val

    for prov, key in keys.items():
        refresh_provider_models(prov, key)


# ── Exceptions ───────────────────────────────────────────────────────────────

class ClaudeCodeRateLimitError(Exception):
    """Raised when Claude Code CLI hits subscription rate/usage limits."""
    pass


# ── Unified client ────────────────────────────────────────────────────────────

class LLMClient:
    """Thin wrapper that exposes a single `message()` method across providers."""

    def __init__(self, provider: str, api_key: str, base_url: str = ""):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self._client = None  # lazily built on first call
        # Cumulative token usage tracking
        self.input_tokens = 0
        self.output_tokens = 0
        # Claude Code CLI fallback state
        self._cc_exhausted = False
        self._fallback_client = None
        self.fallback_activated = False
        self._cc_stderr_warnings: list[str] = []  # stderr output from successful CLI calls

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def reset_usage(self):
        """Reset cumulative token counters to zero."""
        self.input_tokens = 0
        self.output_tokens = 0

    # -- public API ----------------------------------------------------------

    def message(
        self,
        model: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> str:
        """Send a prompt and return the assistant's text response."""
        dispatch = {
            "anthropic":  self._call_anthropic,
            "openai":     self._call_openai,
            "gemini":     self._call_gemini,
            "grok":       self._call_grok,
            "ollama":     self._call_ollama,
            "claude_code": self._call_claude_code,
        }
        fn = dispatch.get(self.provider)
        if fn is None:
            raise ValueError(f"Unknown provider: {self.provider}")
        return fn(model, user_prompt, system_prompt, max_tokens)

    # -- Anthropic -----------------------------------------------------------

    def _call_anthropic(self, model, user, system, max_tokens):
        import anthropic
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
        )
        if system:
            kwargs["system"] = system
        resp = self._client.messages.create(**kwargs)
        if hasattr(resp, "usage") and resp.usage:
            self.input_tokens += getattr(resp.usage, "input_tokens", 0)
            self.output_tokens += getattr(resp.usage, "output_tokens", 0)
        return resp.content[0].text

    # -- OpenAI --------------------------------------------------------------

    def _call_openai(self, model, user, system, max_tokens):
        from openai import OpenAI
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if hasattr(resp, "usage") and resp.usage:
            self.input_tokens += getattr(resp.usage, "prompt_tokens", 0)
            self.output_tokens += getattr(resp.usage, "completion_tokens", 0)
        return resp.choices[0].message.content

    # -- Google Gemini -------------------------------------------------------

    def _call_gemini(self, model, user, system, max_tokens):
        from google import genai
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        config = genai.types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
        if system:
            config.system_instruction = system
        resp = self._client.models.generate_content(
            model=model,
            contents=user,
            config=config,
        )
        if hasattr(resp, "usage_metadata") and resp.usage_metadata:
            um = resp.usage_metadata
            self.input_tokens += getattr(um, "prompt_token_count", 0)
            self.output_tokens += getattr(um, "candidates_token_count", 0)
        return resp.text

    # -- xAI Grok (OpenAI-compatible endpoint) --------------------------------

    def _call_grok(self, model, user, system, max_tokens):
        from openai import OpenAI
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.x.ai/v1",
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if hasattr(resp, "usage") and resp.usage:
            self.input_tokens += getattr(resp.usage, "prompt_tokens", 0)
            self.output_tokens += getattr(resp.usage, "completion_tokens", 0)
        return resp.choices[0].message.content

    # -- Ollama (OpenAI-compatible local endpoint) ----------------------------

    def _call_ollama(self, model, user, system, max_tokens):
        from openai import OpenAI
        base = self.base_url.rstrip("/") if self.base_url else "http://localhost:11434"
        if self._client is None:
            self._client = OpenAI(
                api_key="ollama",
                base_url=f"{base}/v1",
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if hasattr(resp, "usage") and resp.usage:
            self.input_tokens += getattr(resp.usage, "prompt_tokens", 0)
            self.output_tokens += getattr(resp.usage, "completion_tokens", 0)
        return resp.choices[0].message.content

    # -- Claude Code CLI (uses subscription via `claude -p`) -----------------

    def _call_claude_code(self, model, user, system, max_tokens):
        # If a previous call exhausted the rate limit, go straight to fallback
        if self._cc_exhausted:
            return self._call_anthropic_fallback(model, user, system, max_tokens)

        import shutil

        claude_path = shutil.which("claude")
        if not claude_path:
            raise FileNotFoundError(
                "Claude Code CLI ('claude') not found on PATH. "
                "Install it or add it to your PATH. "
                "See: https://docs.anthropic.com/en/docs/claude-code")

        cmd = [claude_path, "-p", "--model", model,
               "--output-format", "json", "--tools", ""]

        # Claude Code's internal system prompt overrides --system-prompt,
        # so we prepend our instructions to the user message instead.
        combined_input = f"{system}\n\n---\n\n{user}" if system else user

        # Strip ANTHROPIC_API_KEY from the subprocess environment so that
        # claude -p uses OAuth/subscription auth instead of the API key.
        env = {k: v for k, v in os.environ.items()
               if k != "ANTHROPIC_API_KEY"}

        try:
            result = subprocess.run(
                cmd, input=combined_input, capture_output=True, text=True,
                encoding="utf-8", timeout=300,
                creationflags=_SUBPROCESS_FLAGS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "Claude Code CLI timed out after 5 minutes. "
                "This may indicate network issues or an unusually long response.")
        except OSError as exc:
            raise RuntimeError(
                f"Failed to launch Claude Code CLI: {exc}. "
                f"Is 'claude' installed and on your PATH?")

        if result.returncode != 0:
            err = result.stderr.strip()
            stdout = result.stdout.strip()
            err_lower = (err + " " + stdout).lower()
            is_rate_limit = any(phrase in err_lower for phrase in (
                "rate limit", "usage limit", "token limit",
                "too many requests", "quota", "capacity", "exceeded",
            ))
            if is_rate_limit:
                self._cc_exhausted = True
                if self.api_key:
                    self.fallback_activated = True
                    return self._call_anthropic_fallback(
                        model, user, system, max_tokens)
                raise ClaudeCodeRateLimitError(
                    f"Claude Code rate limit reached and no fallback API "
                    f"key configured.\n"
                    f"  stderr: {err}\n"
                    f"  Add an Anthropic API key in Settings to enable "
                    f"automatic fallback.")
            # Include both stderr and stdout for diagnosis
            detail = err or stdout or "(no output)"
            raise RuntimeError(
                f"Claude Code CLI exited with code {result.returncode}: "
                f"{detail}")

        stdout = result.stdout.strip()

        # Capture stderr warnings even on success (CLI may emit non-fatal
        # warnings about auth, updates, etc.)
        stderr = result.stderr.strip()
        if stderr:
            self._cc_stderr_warnings.append(stderr)

        # With --output-format json, stdout is a JSON envelope with a
        # "result" field containing the actual LLM text.
        _rate_phrases = (
            "rate limit", "usage limit", "token limit",
            "too many requests", "quota", "capacity", "exceeded",
            "try again later", "billing",
        )
        try:
            envelope = json.loads(stdout)
            content = envelope.get("result", "")
            is_error = envelope.get("is_error", False)
            if is_error:
                err_lower = content.lower()
                if any(p in err_lower for p in _rate_phrases):
                    self._cc_exhausted = True
                    if self.api_key:
                        self.fallback_activated = True
                        return self._call_anthropic_fallback(
                            model, user, system, max_tokens)
                    raise ClaudeCodeRateLimitError(
                        f"Claude Code rate limit reached.\n"
                        f"  {content[:300]}\n"
                        f"  Add an Anthropic API key in Settings to enable "
                        f"automatic fallback.")
                raise RuntimeError(
                    f"Claude Code CLI error: {content[:500]}")
            return content
        except (json.JSONDecodeError, KeyError):
            # Fallback: stdout wasn't valid JSON envelope (older CLI?)
            stdout_lower = stdout.lower()
            if any(p in stdout_lower for p in _rate_phrases):
                self._cc_exhausted = True
                if self.api_key:
                    self.fallback_activated = True
                    return self._call_anthropic_fallback(
                        model, user, system, max_tokens)
                raise ClaudeCodeRateLimitError(
                    f"Claude Code rate limit reached (non-JSON "
                    f"response).\n  stdout: {stdout[:300]}\n"
                    f"  Add an Anthropic API key in Settings to enable "
                    f"automatic fallback.")
            return stdout

    # -- Anthropic API fallback (used when Claude Code CLI is rate-limited) ---

    def _call_anthropic_fallback(self, model, user, system, max_tokens):
        import anthropic
        if self._fallback_client is None:
            self._fallback_client = anthropic.Anthropic(api_key=self.api_key)
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
        )
        if system:
            kwargs["system"] = system
        resp = self._fallback_client.messages.create(**kwargs)
        if hasattr(resp, "usage") and resp.usage:
            self.input_tokens += getattr(resp.usage, "input_tokens", 0)
            self.output_tokens += getattr(resp.usage, "output_tokens", 0)
        return resp.content[0].text


def make_client(provider: str, api_key: str, base_url: str = "") -> LLMClient:
    """Create an LLMClient for the given provider."""
    return LLMClient(provider, api_key, base_url=base_url)
