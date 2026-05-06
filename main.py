"""
Main orchestrator: scrape packages, store in SQLite, notify via Pushover.

Usage:
    python main.py               # scrape + send alerts
    python main.py --dry-run     # scrape only, print what would be sent
    python main.py --no-scrape   # skip scraping, just retry sending unsent alerts

Environment (loaded from .env):
    AWS_USERNAME          AWS Cargo username
    AWS_PASSWORD          AWS Cargo password
    PUSHOVER_USER         Pushover user key
    PUSHOVER_TOKEN        Pushover app token (default)
    PUSHOVER_TOKEN_AWS    Pushover app token (optional)
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

from db import init_db, insert_or_update_package, get_unsent_packages, mark_as_sent
from scraper import scrape_packages
from notifier import send_package_alert


def main() -> None:
    parser = argparse.ArgumentParser(description="AWS Cargo scraper + Pushover alerts")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without actually contacting Pushover or marking sent",
    )
    parser.add_argument(
        "--no-scrape",
        action="store_true",
        help="Skip scraping; only retry sending existing unsent alerts from DB",
    )
    parser.add_argument(
        "--aws-token",
        action="store_true",
        help="Use PUSHOVER_TOKEN_AWS instead of PUSHOVER_TOKEN",
    )
    args = parser.parse_args()

    db_name = os.getenv("DB_NAME", "packages.db").strip() or "packages.db"

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
            insert_or_update_package(
                tracking=pkg["tracking"],
                description=pkg.get("description") or None,
                price=pkg.get("price") or None,
                status=pkg.get("status") or None,
                last_updated=pkg.get("last_updated") or None,
                db_name=db_name,
            )
    else:
        print("[main] --no-scrape passed; skipping scrape.")

    # ── Phase 2: Notify unsent ─────────────────────────────────────────
    unsent = get_unsent_packages(db_name)
    if not unsent:
        print("[main] No unsent packages. Nothing to do.")
        return

    print(f"[main] {len(unsent)} unsent package(s) to alert.")
    for pkg in unsent:
        tracking = pkg["tracking"]
        status   = pkg.get("status", "N/A")
        print(f"  -> {tracking} [{status}]")
        if args.dry_run:
            print("    (dry-run: not sending)")
            continue
        try:
            send_package_alert(pkg, use_aws_token=args.aws_token)
            mark_as_sent(tracking, db_name)
            print("    Pushover OK, marked as sent.")
        except Exception as exc:
            print(f"    Pushover FAILED for {tracking}: {exc}")

    print("[main] Done.")


if __name__ == "__main__":
    main()
