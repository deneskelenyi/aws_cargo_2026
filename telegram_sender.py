"""
Telegram sender via the machucavalley webhook API.

Environment (loaded from .env by callers or at import time):
    WEBHOOK_HOST      Base host, e.g. https://your-webhook-host.example
    WEBHOOK_PATH      Path prefix, e.g. /webhooktg/  (default: /webhooktg/)
    SEND_API_URL      Optional full URL override, e.g. https://host/webhooktg/sendapi/
    SEND_API_KEY      API key for the X-API-Key / Authorization headers
    TELEGRAM_RECIPIENT Default chat_id if none is passed to send_message()

This mirrors the logic in telegram_sender_test.py but exposes a simple
send_message(text, chat_id) function usable by the notifier.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


def _load_env_once() -> None:
    """Load .env if python-dotenv is available and variables are not already set."""
    if os.getenv("SEND_API_KEY"):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass


def _api_url() -> str:
    """Build the send API URL from environment variables."""
    explicit = os.environ.get("SEND_API_URL", "").strip()
    if explicit:
        return explicit.rstrip("/") + "/"

    host = os.environ.get("WEBHOOK_HOST", "").strip().rstrip("/")
    if not host:
        raise ValueError("WEBHOOK_HOST or SEND_API_URL must be set in environment / .env")
    path = os.environ.get("WEBHOOK_PATH", "/webhooktg/").strip()
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return f"{host}{path}sendapi/"


def _api_key() -> str:
    """Return the configured SEND_API_KEY, stripped of surrounding quotes."""
    key = (os.environ.get("SEND_API_KEY") or "").strip().strip('"').strip("'")
    if not key:
        raise ValueError("SEND_API_KEY not found in environment / .env")
    return key


def _default_chat_id() -> Optional[int]:
    """Return TELEGRAM_RECIPIENT as an int if it is set."""
    raw = os.environ.get("TELEGRAM_RECIPIENT", "").strip()
    if raw:
        return int(raw)
    return None


def send_message(
    text: str,
    chat_id: Optional[int] = None,
    *,
    user_agent: Optional[str] = None,
) -> dict:
    """
    Send a text message through the Telegram webhook API.

    Args:
        text: Message text (Markdown is supported by Telegram).
        chat_id: Target chat; defaults to TELEGRAM_RECIPIENT env var.
        user_agent: Optional custom User-Agent header.

    Returns:
        Parsed JSON response as a dict.

    Raises:
        ValueError: if credentials or chat_id are missing.
        urllib.error.HTTPError: on non-2xx responses.
    """
    _load_env_once()

    key = _api_key()
    chat_id = chat_id or _default_chat_id()
    if chat_id is None:
        raise ValueError("chat_id not provided and TELEGRAM_RECIPIENT not set")

    url = _api_url()
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")

    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": ua,
        "X-API-Key": key,
        "Authorization": f"Bearer {key}",
    }

    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_configured() -> bool:
    """Return True if the Telegram sender appears to be configured."""
    _load_env_once()
    try:
        _api_key()
        return _default_chat_id() is not None
    except ValueError:
        return False
