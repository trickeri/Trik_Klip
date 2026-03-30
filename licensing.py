"""
Gumroad license-key verification for Trik_Klip.

API reference: POST https://api.gumroad.com/v2/licenses/verify
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from dataclasses import dataclass

GUMROAD_VERIFY_URL = "https://api.gumroad.com/v2/licenses/verify"

# ── UPDATE THIS with your Gumroad product ID ────────────────────────────────
PRODUCT_ID = "G0vf5cY8nEQ8Cms7kstMuQ=="

def _license_path() -> Path:
    """Store the license in %APPDATA%/Trik_Klip so it survives rebuilds."""
    import os
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / "Trik_Klip"
        d.mkdir(exist_ok=True)
        return d / ".trik_klip_license"
    return Path(__file__).parent / ".trik_klip_license"

LICENSE_PATH = _license_path()


@dataclass
class LicenseResult:
    valid: bool
    message: str
    uses: int = 0
    test: bool = False


def verify_license(license_key: str, increment_uses: bool = True) -> LicenseResult:
    """Verify a license key against the Gumroad API.

    Args:
        license_key: The Gumroad license key to verify.
        increment_uses: Whether to count this as a new activation.

    Returns:
        LicenseResult with validation status and details.
    """
    data = urllib.parse.urlencode({
        "product_id": PRODUCT_ID,
        "license_key": license_key.strip(),
        "increment_uses_count": str(increment_uses).lower(),
    }).encode("utf-8")

    req = urllib.request.Request(GUMROAD_VERIFY_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return LicenseResult(valid=False, message="License key not found.")
        try:
            body = json.loads(exc.read().decode("utf-8"))
            return LicenseResult(
                valid=False,
                message=body.get("message", f"Verification failed (HTTP {exc.code})."),
            )
        except Exception:
            return LicenseResult(valid=False, message=f"Verification failed (HTTP {exc.code}).")
    except urllib.error.URLError:
        # No internet — allow offline use if previously activated
        if load_saved_license() is not None:
            return LicenseResult(valid=True, message="Offline mode (previously activated).")
        return LicenseResult(valid=False, message="No internet connection. Cannot verify license.")
    except Exception as exc:
        return LicenseResult(valid=False, message=f"Unexpected error: {exc}")

    success = body.get("success", False)
    purchase = body.get("purchase", {})
    uses = body.get("uses", 0)
    is_test = purchase.get("test", False)

    if success:
        return LicenseResult(valid=True, message="License verified.", uses=uses, test=is_test)
    else:
        return LicenseResult(
            valid=False,
            message=body.get("message", "License verification failed."),
            uses=uses,
        )


def save_license(license_key: str) -> None:
    """Persist a validated license key to disk."""
    LICENSE_PATH.write_text(
        json.dumps({"license_key": license_key.strip()}, indent=2),
        encoding="utf-8",
    )


def load_saved_license() -> str | None:
    """Load a previously saved license key, or None if not found."""
    if not LICENSE_PATH.exists():
        return None
    try:
        data = json.loads(LICENSE_PATH.read_text(encoding="utf-8"))
        return data.get("license_key")
    except Exception:
        return None


def clear_license() -> None:
    """Remove the saved license file."""
    if LICENSE_PATH.exists():
        LICENSE_PATH.unlink()
