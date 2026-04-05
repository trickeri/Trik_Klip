// Gumroad license verification with offline cache.
// Ported from Python licensing.py.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tracing::warn;

const GUMROAD_VERIFY_URL: &str = "https://api.gumroad.com/v2/licenses/verify";
const PRODUCT_ID: &str = "G0vf5cY8nEQ8Cms7kstMuQ==";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LicenseResult {
    pub valid: bool,
    pub message: String,
    pub uses: u32,
    pub test: bool,
}

/// Gumroad API response (partial).
#[derive(Debug, Deserialize)]
struct GumroadResponse {
    #[serde(default)]
    success: bool,
    #[serde(default)]
    message: Option<String>,
    #[serde(default)]
    uses: u32,
    #[serde(default)]
    purchase: Option<GumroadPurchase>,
}

#[derive(Debug, Deserialize)]
struct GumroadPurchase {
    #[serde(default)]
    test: bool,
}

/// Verify a license key against the Gumroad API.
///
/// On network error, allows offline use if a license was previously saved.
pub async fn verify_license(
    client: &reqwest::Client,
    license_key: &str,
    increment_uses: bool,
) -> LicenseResult {
    let params = [
        ("product_id", PRODUCT_ID),
        ("license_key", license_key.trim()),
        (
            "increment_uses_count",
            if increment_uses { "true" } else { "false" },
        ),
    ];

    let response = match client
        .post(GUMROAD_VERIFY_URL)
        .form(&params)
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            warn!("Network error verifying license: {}", e);
            // No internet — allow offline use if previously activated
            if load_saved_license().is_some() {
                return LicenseResult {
                    valid: true,
                    message: "Offline mode (previously activated).".to_owned(),
                    uses: 0,
                    test: false,
                };
            }
            return LicenseResult {
                valid: false,
                message: "No internet connection. Cannot verify license.".to_owned(),
                uses: 0,
                test: false,
            };
        }
    };

    let status = response.status();

    if status == reqwest::StatusCode::NOT_FOUND {
        return LicenseResult {
            valid: false,
            message: "License key not found.".to_owned(),
            uses: 0,
            test: false,
        };
    }

    let body_text = match response.text().await {
        Ok(t) => t,
        Err(e) => {
            return LicenseResult {
                valid: false,
                message: format!("Failed to read response: {}", e),
                uses: 0,
                test: false,
            };
        }
    };

    if !status.is_success() {
        // Try to extract message from error body
        if let Ok(parsed) = serde_json::from_str::<GumroadResponse>(&body_text) {
            return LicenseResult {
                valid: false,
                message: parsed
                    .message
                    .unwrap_or_else(|| format!("Verification failed (HTTP {}).", status)),
                uses: 0,
                test: false,
            };
        }
        return LicenseResult {
            valid: false,
            message: format!("Verification failed (HTTP {}).", status),
            uses: 0,
            test: false,
        };
    }

    let parsed: GumroadResponse = match serde_json::from_str(&body_text) {
        Ok(p) => p,
        Err(e) => {
            return LicenseResult {
                valid: false,
                message: format!("Unexpected response format: {}", e),
                uses: 0,
                test: false,
            };
        }
    };

    let is_test = parsed.purchase.map(|p| p.test).unwrap_or(false);

    if parsed.success {
        LicenseResult {
            valid: true,
            message: "License verified.".to_owned(),
            uses: parsed.uses,
            test: is_test,
        }
    } else {
        LicenseResult {
            valid: false,
            message: parsed
                .message
                .unwrap_or_else(|| "License verification failed.".to_owned()),
            uses: parsed.uses,
            test: false,
        }
    }
}

/// Return the path to the stored license file.
///
/// `%APPDATA%/Trik_Klip/.trik_klip_license` on Windows,
/// falls back to the current directory if `APPDATA` is unset.
fn license_path() -> PathBuf {
    if let Ok(appdata) = std::env::var("APPDATA") {
        let dir = PathBuf::from(appdata).join("Trik_Klip");
        // best-effort create
        let _ = std::fs::create_dir_all(&dir);
        dir.join(".trik_klip_license")
    } else {
        PathBuf::from(".trik_klip_license")
    }
}

/// Persist a validated license key to disk.
pub fn save_license(license_key: &str) -> anyhow::Result<()> {
    let path = license_path();
    let data = serde_json::json!({ "license_key": license_key.trim() });
    std::fs::write(&path, serde_json::to_string_pretty(&data)?)?;
    Ok(())
}

/// Load a previously saved license key, or `None` if not found.
pub fn load_saved_license() -> Option<String> {
    let path = license_path();
    let contents = std::fs::read_to_string(&path).ok()?;
    let data: serde_json::Value = serde_json::from_str(&contents).ok()?;
    data.get("license_key")?.as_str().map(|s| s.to_owned())
}

/// Remove the saved license file.
pub fn clear_license() -> anyhow::Result<()> {
    let path = license_path();
    if path.exists() {
        std::fs::remove_file(&path)?;
    }
    Ok(())
}
