"""Local dashboard form safety helpers."""

import hmac
from hashlib import sha256

from ai_media_os.infrastructure.settings import AppSettings, get_settings


class DashboardSecurityError(RuntimeError):
    """Raised when dashboard form safety validation fails."""


def csrf_token(settings: AppSettings | None = None) -> str:
    resolved = settings or get_settings()
    return hmac.new(
        resolved.dashboard_csrf_secret.encode("utf-8"),
        b"ai-media-os-local-dashboard",
        sha256,
    ).hexdigest()


def validate_csrf_token(token: str | None, settings: AppSettings | None = None) -> None:
    expected = csrf_token(settings)
    if token is None or not hmac.compare_digest(token, expected):
        raise DashboardSecurityError("Invalid form safety token.")
