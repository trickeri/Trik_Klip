// Resolve the backend base URL at runtime. The Tauri host picks a free port
// in 31416..=31430 on startup (so multiple instances of the app can run at
// once) and exposes it through the `get_api_port` command. We cache the
// resolved URL in a promise so it's only fetched once per session.
let _baseUrlPromise: Promise<string> | null = null;

export function getApiBase(): Promise<string> {
  if (!_baseUrlPromise) {
    _baseUrlPromise = (async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const port = await invoke<number>("get_api_port");
        return `http://127.0.0.1:${port}`;
      } catch (e) {
        console.warn("[api] Failed to read port from Tauri, falling back to 31416", e);
        return "http://127.0.0.1:31416";
      }
    })();
  }
  return _baseUrlPromise;
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const base = await getApiBase();
  const res = await fetch(`${base}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function healthCheck(): Promise<{ status: string }> {
  return apiFetch("/health");
}
