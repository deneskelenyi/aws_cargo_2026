"""
Main orchestrator: scrape packages, store in SQLite, notify via Pushover/Telegram.

Usage:
    python main.py               # scrape + check public tracking + send consolidated alerts
    python main.py --dry-run     # scrape only, print what would be sent
    python main.py --no-scrape   # skip scraping, just retry sending unsent alerts
    python main.py --no-external # skip the public tracking check for unlinked items
    python main.py --individual  # send one alert per package instead of consolidating

Environment (loaded from .env):
    AWS_USERNAME          AWS Cargo username
    AWS_PASSWORD          AWS Cargo password
    PUSHOVER_USER         Pushover user key
    PUSHOVER_TOKEN        Pushover app token (default)
    PUSHOVER_TOKEN_AWS    Pushover app token (optional)
    WEBHOOK_HOST          Telegram webhook base host
    WEBHOOK_PATH          Telegram webhook path prefix
    SEND_API_KEY          Telegram webhook API key
    TELEGRAM_RECIPIENT    Default Telegram chat id
    CAMOFOX_URL           Optional Camoufox REST server URL
    DB_NAME               Optional custom SQLite path (default: packages.db)
"""
import argparse
import os
import sys
from pathlib import Path

# Load .env before any other imports so DB/scraper/notifier see the variables.
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_PATH = _SCRIPT_DIR / ".env"
if _ENV_PATH.is_file():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    load_dotenv()

from db import (
    init_db,
    insert_or_update_package,
    get_unsent_packages,
    mark_as_sent,
    get_unlinked_items,
    upsert_external_tracking,
    delete_external_tracking,
)
from external_tracker import fetch_tracking
from scraper import scrape_packages
from notifier import send_consolidated_alert, send_package_alert


def main() -> None:
    parser = argparse.ArgumentParser(description="AWS Cargo scraper + Pushover/Telegram alerts")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without actually contacting Pushover/Telegram or marking sent",
    )
    parser.add_argument(
        "--no-scrape",
        action="store_true",
        help="Skip scraping; only retry sending existing unsent alerts from DB",
    )
    parser.add_argument(
        "--no-external",
        action="store_true",
        help="Skip the public tracking check for items not yet in the internal system",
    )
    parser.add_argument(
        "--aws-token",
        action="store_true",
        help="Use PUSHOVER_TOKEN_AWS instead of PUSHOVER_TOKEN",
    )
    parser.add_argument(
        "--individual",
        action="store_true",
        help="Send one alert per package instead of a single consolidated message",
    )
    args = parser.parse_args()

    db_name = os.getenv("DB_NAME", "").strip() or str(_SCRIPT_DIR / "packages.db")

    # Ensure database exists.
    init_db(db_name)

    # ── Phase 1: Scrape ────────────────────────────────────────────────
    if not args.no_scrape:
        print("[main] Scraping packages...")
        try:
            packages = scrape_packages()
        except Exception as exc:
            print(f"[main] Scraping FAILED: {exc}")
            sys.exit(1)

        print(f"[main] Persisting {len(packages)} rows...")
        for pkg in packages:
            result = insert_or_update_package(
                tracking=pkg["tracking"],
                description=pkg.get("description") or None,
                price=pkg.get("price") or None,
                status=pkg.get("status") or None,
                last_updated=pkg.get("last_updated") or None,
                db_name=db_name,
            )
            tags = []
            if result["was_new"]:
                tags.append("new")
            if result["status_changed"]:
                tags.append("status changed")
            tag_str = f" ({', '.join(tags)})" if tags else ""
            print(f"  -> {pkg['tracking']}{tag_str}")
    else:
        print("[main] --no-scrape passed; skipping scrape.")

    # ── Phase 1b: Public tracking for items not yet in the system ──────
    if not args.no_scrape and not args.no_external:
        print("[main] Checking public tracking API for unlinked items...")
        import json as _json
        import time as _time

        unlinked = get_unlinked_items(db_name)
        # Deduplicate tracking numbers while keeping order.
        seen: dict[str, None] = {}
        for item in unlinked:
            t = (item.get("tracking") or "").strip()
            if t:
                seen.setdefault(t)
        print(f"[main] {len(seen)} unique unlinked tracking number(s).")

        found = 0
        for i, tracking in enumerate(seen, start=1):
            # Polite delay between requests (skip before the first one).
            if i > 1:
                _time.sleep(2)
            try:
                info = fetch_tracking(tracking)
            except Exception as exc:
                print(f"  -> {tracking}: API error ({exc})")
                continue
            if info is None:
                print(f"  -> {tracking}: not on public tracking yet")
                # Drop any stale row so the web UI doesn't show old data.
                delete_external_tracking(tracking, db_name)
                continue
            upsert_external_tracking(
                tracking=tracking,
                status=info["status"],
                status_label=info["status_label"],
                last_updated=info["last_updated"],
                events=_json.dumps(info["events"]),
                db_name=db_name,
            )
            found += 1
            print(f"  -> {tracking}: {info['status_label']} ({info['last_updated']})")
        print(f"[main] Public tracking: {found} of {len(seen)} number(s) found.")
    elif args.no_external:
        print("[main] --no-external passed; skipping public tracking check.")

    # ── Phase 2: Notify unsent ─────────────────────────────────────────
    unsent = get_unsent_packages(db_name)
    if not unsent:
        print("[main] No unsent packages. Nothing to do.")
        return

    print(f"[main] {len(unsent)} unsent package(s) to alert.")
    for pkg in unsent:
        tracking = pkg["tracking"]
        status = pkg.get("status", "N/A")
        print(f"  -> {tracking} [{status}]")

    if args.dry_run:
        print("[main] (dry-run: not sending)")
        print("[main] Done.")
        return

    if args.individual:
        for pkg in unsent:
            tracking = pkg["tracking"]
            try:
                send_package_alert(pkg, use_aws_token=args.aws_token, db_name=db_name)
                mark_as_sent(tracking, db_name)
                print(f"    Alert sent for {tracking}.")
            except Exception as exc:
                print(f"    Alert FAILED for {tracking}: {exc}")
    else:
        try:
            result = send_consolidated_alert(
                unsent, use_aws_token=args.aws_token, db_name=db_name
            )
            for pkg in unsent:
                mark_as_sent(pkg["tracking"], db_name)
            chunks = []
            if result.get("pushover"):
                chunks.append(f"Pushover {result['pushover']['chunks']} chunk(s)")
            if result.get("telegram"):
                chunks.append(f"Telegram {result['telegram']['chunks']} chunk(s)")
            chunk_str = f" ({', '.join(chunks)})" if chunks else ""
            print(f"[main] Consolidated alert sent for {len(unsent)} package(s){chunk_str}.")
        except Exception as exc:
            print(f"[main] Consolidated alert FAILED: {exc}")

    print("[main] Done.")


if __name__ == "__main__":
    main()
