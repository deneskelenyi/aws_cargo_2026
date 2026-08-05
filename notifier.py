"""
Notification dispatcher for AWS Cargo package updates.

Supports two channels:
    * Pushover (legacy)  -- PUSHOVER_USER + PUSHOVER_TOKEN / PUSHOVER_TOKEN_AWS
    * Telegram           -- WEBHOOK_HOST + WEBHOOK_PATH + SEND_API_KEY + TELEGRAM_RECIPIENT

If a tracking number has friendly item names stored in the DB, they are included
in the alert message.

Alerts can be sent one-per-package or consolidated into fewer messages. Consolidation
is the default because the scraper runs hourly and several packages may arrive at once.
"""
import os
from typing import Any, Optional

import requests

from db import get_item_names_for_tracking
from telegram_sender import is_configured as telegram_is_configured, send_message as send_telegram

PUSHOVER_API = "https://api.pushover.net/1/messages.json"

# Platform message-length limits (body/text only).
PUSHOVER_MSG_LIMIT = 1024
TELEGRAM_MSG_LIMIT = 4096


def pushover_is_configured(use_aws_token: bool = False) -> bool:
    """Return True if Pushover credentials are present."""
    token = os.getenv("PUSHOVER_TOKEN_AWS" if use_aws_token else "PUSHOVER_TOKEN", "").strip()
    user = os.getenv("PUSHOVER_USER", "").strip()
    return bool(token and user)


def _get_pushover_token(use_aws_token: bool = False) -> str:
    """Read Pushover token from env."""
    key = "PUSHOVER_TOKEN_AWS" if use_aws_token else "PUSHOVER_TOKEN"
    token = os.getenv(key, "").strip()
    if not token:
        raise ValueError(f"{key} not found in environment / .env")
    return token


def send_pushover_notification(
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
        title:      Message title.
        message:    Body text.
        use_aws_token: If True, use PUSHOVER_TOKEN_AWS instead of default.
        priority:   -2 lowest, -1 low, 0 normal, 1 high, 2 emergency.
        sound:      One of Pushover sounds or None for app default.

    Returns:
        Parsed JSON response from Pushover.
    """
    token = _get_pushover_token(use_aws_token)
    user = os.getenv("PUSHOVER_USER", "").strip()
    if not user:
        raise ValueError("PUSHOVER_USER not found in environment / .env")

    payload = {
        "token": token,
        "user": user,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if sound:
        payload["sound"] = sound

    resp = requests.post(PUSHOVER_API, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _format_message(pkg: dict, item_names: list[str]) -> str:
    """Build the human-readable alert body for a single package."""
    tracking = pkg.get("tracking", "N/A")
    status = pkg.get("status", "N/A")
    price = pkg.get("price", "N/A")
    desc = pkg.get("description") or "No description"

    lines = [
        f"Status: {status}",
        f"Price:  {price}",
        f"Desc:   {desc}",
    ]
    if item_names:
        lines.append(f"Items:  {', '.join(item_names)}")
    else:
        lines.append("Items:  (none linked)")

    return f"AWS Cargo – {tracking}\n" + "\n".join(lines)


def _status_priority(status: Optional[str]) -> int:
    """Choose a Pushover priority based on the package status."""
    if not status:
        return 0
    terminal = ("delivered", "received", "ready for pickup", "listo para recoger")
    if status.lower() in terminal:
        return 1
    return 0


def _chunk_blocks(blocks: list[str], header: str, max_len: int) -> list[str]:
    """
    Greedily group package blocks into messages that do not exceed max_len.

    Individual package blocks are never split; if one block alone exceeds the
    limit it is still emitted as its own message.
    """
    chunks: list[str] = []
    current: list[str] = []

    for block in blocks:
        candidate = header + "\n\n" + "\n\n".join(current + [block])
        if len(candidate) > max_len and current:
            chunks.append(header + "\n\n" + "\n\n".join(current))
            current = [block]
        else:
            current.append(block)

    if current:
        chunks.append(header + "\n\n" + "\n\n".join(current))

    return chunks


def _build_blocks(
    packages: list[dict], db_name: Optional[str]
) -> list[str]:
    """Convert package rows into formatted message blocks."""
    blocks = []
    for pkg in packages:
        tracking = pkg.get("tracking", "N/A")
        item_names = get_item_names_for_tracking(tracking, db_name)
        blocks.append(_format_message(pkg, item_names))
    return blocks


def send_package_alert(
    pkg: dict,
    *,
    use_aws_token: bool = False,
    db_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Send an alert for a single package row.

    Sends to every configured channel (Pushover and/or Telegram). Raises only
    if *no* channel was configured; otherwise partial failures are collected
    in the returned dict.
    """
    tracking = pkg.get("tracking", "N/A")
    status = pkg.get("status", "N/A")
    item_names = get_item_names_for_tracking(tracking, db_name)
    message = _format_message(pkg, item_names)

    results = {
        "tracking": tracking,
        "pushover": None,
        "telegram": None,
    }
    errors = []

    if pushover_is_configured(use_aws_token):
        try:
            title = f"AWS Cargo – {tracking} [{status}]"
            results["pushover"] = send_pushover_notification(
                title=title,
                message=message,
                use_aws_token=use_aws_token,
                priority=_status_priority(status),
            )
        except Exception as exc:
            results["pushover"] = {"error": str(exc)}
            errors.append(f"Pushover: {exc}")

    if telegram_is_configured():
        try:
            results["telegram"] = send_telegram(message)
        except Exception as exc:
            results["telegram"] = {"error": str(exc)}
            errors.append(f"Telegram: {exc}")

    if not pushover_is_configured(use_aws_token) and not telegram_is_configured():
        raise RuntimeError(
            "No notification channel configured. "
            "Set Pushover (PUSHOVER_USER/PUSHOVER_TOKEN) or Telegram "
            "(WEBHOOK_HOST/WEBHOOK_PATH/SEND_API_KEY/TELEGRAM_RECIPIENT) in .env."
        )

    if errors:
        results["errors"] = errors
        raise RuntimeError("; ".join(errors))

    return results


def send_consolidated_alert(
    packages: list[dict],
    *,
    use_aws_token: bool = False,
    db_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Send a single consolidated alert for all supplied packages.

    The message is split into multiple platform messages if it exceeds the
    service limit:
        Pushover: {PUSHOVER_MSG_LIMIT} chars
        Telegram: {TELEGRAM_MSG_LIMIT} chars

    On any error the function raises; callers should therefore treat a
    consolidated run as all-or-nothing when marking packages as sent.
    """
    if not packages:
        return {"tracking_count": 0, "pushover": None, "telegram": None}

    blocks = _build_blocks(packages, db_name)
    count = len(packages)
    header = f"AWS Cargo updates – {count} package{'s' if count != 1 else ''}"

    results = {
        "tracking_count": count,
        "pushover": None,
        "telegram": None,
    }
    errors = []

    if pushover_is_configured(use_aws_token):
        try:
            chunks = _chunk_blocks(blocks, header, PUSHOVER_MSG_LIMIT)
            priority = max(
                (_status_priority(pkg.get("status")) for pkg in packages),
                default=0,
            )
            title = f"AWS Cargo – {count} update{'s' if count != 1 else ''}"
            responses = [
                send_pushover_notification(
                    title=title,
                    message=chunk,
                    use_aws_token=use_aws_token,
                    priority=priority,
                )
                for chunk in chunks
            ]
            results["pushover"] = {"chunks": len(chunks), "responses": responses}
        except Exception as exc:
            results["pushover"] = {"error": str(exc)}
            errors.append(f"Pushover: {exc}")

    if telegram_is_configured():
        try:
            chunks = _chunk_blocks(blocks, header, TELEGRAM_MSG_LIMIT)
            responses = [send_telegram(chunk) for chunk in chunks]
            results["telegram"] = {"chunks": len(chunks), "responses": responses}
        except Exception as exc:
            results["telegram"] = {"error": str(exc)}
            errors.append(f"Telegram: {exc}")

    if not pushover_is_configured(use_aws_token) and not telegram_is_configured():
        raise RuntimeError(
            "No notification channel configured. "
            "Set Pushover (PUSHOVER_USER/PUSHOVER_TOKEN) or Telegram "
            "(WEBHOOK_HOST/WEBHOOK_PATH/SEND_API_KEY/TELEGRAM_RECIPIENT) in .env."
        )

    if errors:
        results["errors"] = errors
        raise RuntimeError("; ".join(errors))

    return results
