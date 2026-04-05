use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Settings {
    pub data_dir: String,
    pub database_url: String,
    pub api_port: u16,
    pub ffmpeg_path: String,
    pub ffprobe_path: String,
    pub whisper_cli_path: String,
    pub whisper_model_path: String,
    pub anthropic_api_key: String,
    pub openai_api_key: String,
    pub gemini_api_key: String,
    pub xai_api_key: String,
    pub ollama_base_url: String,
}

impl Settings {
    /// Load settings before tracing is initialized (no log calls).
    pub fn load_early() -> anyhow::Result<Self> {
        let env_paths = Self::env_search_paths();
        for path in &env_paths {
            if path.exists() {
                let _ = dotenvy::from_path(path);
                break;
            }
        }
        Self::build()
    }

    fn build() -> anyhow::Result<Self> {
        let data_dir = Self::resolve_data_dir();
        std::fs::create_dir_all(&data_dir)?;

        let db_path = PathBuf::from(&data_dir).join("trik_klip.db");
        let database_url = format!("sqlite:{}?mode=rwc", db_path.display());

        // Resolve resource paths (next to exe in production, or CWD in dev)
        let resources_dir = Self::resolve_resources_dir();

        Ok(Settings {
            data_dir,
            database_url,
            api_port: env_or("API_PORT", "31416").parse().unwrap_or(31416),
            ffmpeg_path: env_or("FFMPEG_PATH", "ffmpeg"),
            ffprobe_path: env_or("FFPROBE_PATH", "ffprobe"),
            whisper_cli_path: env_or(
                "WHISPER_CLI_PATH",
                &resources_dir.join("whisper-cli.exe").to_string_lossy(),
            ),
            whisper_model_path: env_or(
                "WHISPER_MODEL_PATH",
                &resources_dir.join("ggml-base.bin").to_string_lossy(),
            ),
            anthropic_api_key: env_or("ANTHROPIC_API_KEY", ""),
            openai_api_key: env_or("OPENAI_API_KEY", ""),
            gemini_api_key: env_or("GEMINI_API_KEY", ""),
            xai_api_key: env_or("XAI_API_KEY", ""),
            ollama_base_url: env_or("OLLAMA_BASE_URL", "http://localhost:11434"),
        })
    }

    fn resolve_data_dir() -> String {
        if let Some(appdata) = std::env::var_os("APPDATA") {
            let p = PathBuf::from(appdata).join("Trik_Klip").join("data");
            return p.to_string_lossy().into_owned();
        }
        String::from("data")
    }

    fn resolve_resources_dir() -> PathBuf {
        // In production (packaged by Tauri), resources are next to the exe
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                let resources = dir.join("resources");
                if resources.exists() {
                    return resources;
                }
                // Also check _up_ one level (for NSIS layout)
                let alt = dir.join("_up_").join("resources");
                if alt.exists() {
                    return alt;
                }
            }
        }
        // Dev fallback
        PathBuf::from("src-tauri/resources")
    }

    fn env_search_paths() -> Vec<PathBuf> {
        let mut paths = Vec::new();

        // Next to the exe
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                paths.push(dir.join(".env"));
            }
        }

        // AppData
        if let Some(appdata) = std::env::var_os("APPDATA") {
            paths.push(PathBuf::from(appdata).join("Trik_Klip").join(".env"));
        }

        // CWD
        paths.push(PathBuf::from(".env"));

        paths
    }
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}
