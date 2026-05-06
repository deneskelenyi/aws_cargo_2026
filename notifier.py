"""
Pushover notification sender.

Supports two tokens:
    PUSHOVER_TOKEN       — default app token
    PUSHOVER_TOKEN_AWS   — AWS-specific app token (used if AWS-specific option enabled)

Set these plus PUSHOVER_USER in .env.

API docs: https://pushover.net/api
"""
import os
import requests
from typing import Any, Optional

PUSHOVER_API = "https://api.pushover.net/1/messages.json"


def _get_token(use_aws_token: bool = False) -> str:
    """Read token from env."""
    key = "PUSHOVER_TOKEN_AWS" if use_aws_token else "PUSHOVER_TOKEN"
    token = os.getenv(key, "").strip()
    if not token:
        raise ValueError(f"{key} not found in environment / .env")
    return token


def send_notification(
    title: str,
    message: str,
    *,
    use_aws_token: bool = False,
    priority: int = 0,
    sound: Optional[str] = None,
) -> dict:
    """
    Send a single Pushover message.

    Args:
        title:      Message title (app name shows above it in Pushover).
        message:    Body text.
        use_aws_token: If True, use PUSHOVER_TOKEN_AWS instead of default.
        priority:   -2 = lowest, -1 = low, 0 = normal, 1 = high, 2 = emergency
        sound:      One of Pushover sounds or None for app default.

    Returns:
        Parsed JSON response from Pushover.
    """
    token = _get_token(use_aws_token)
    user = os.getenv("PUSHOVER_USER", "").strip()
    if not user:
        raise ValueError("PUSHOVER_USER not found in environment / .env")

    payload = {
        "token":    token,
        "user":     user,
        "title":    title,
        "message":  message,
        "priority": priority,
    }
    if sound:
        payload["sound"] = sound

    resp = requests.post(PUSHOVER_API, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_package_alert(pkg: dict, *, use_aws_token: bool = False) -> dict:
    """
    Send a Pushover alert for a single package row.

    Handles optional empty description gracefully.
    """
    tracking = pkg.get("tracking", "N/A")
    status   = pkg.get("status", "N/A")
    price    = pkg.get("price", "N/A")
    desc     = pkg.get("description") or "No description"

    title = f"AWS Cargo – {tracking}"
    msg = (
        f"Status: {status}\n"
        f"Price:  {price}\n"
        f"Desc:   {desc}"
    )

    return send_notification(
        title=title,
        message=msg,
        use_aws_token=use_aws_token,
        priority=1 if status.lower() in ("delivered", "received", "ready for pickup") else 0,
    )
