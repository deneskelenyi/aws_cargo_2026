"""
Database layer for AWS Cargo package scraper.

Schema:
    packages
        id            INTEGER PRIMARY KEY AUTOINCREMENT
        tracking      TEXT UNIQUE NOT NULL      -- package tracking number
        description   TEXT                       -- user description (often '-')
        price         TEXT                       -- price string (e.g. '$ 28.40')
        status        TEXT                       -- latest status (e.g. 'Delivered')
        last_updated  TEXT                       -- last update timestamp from site
        created_at    TEXT DEFAULT (datetime('now'))
        notified_at   TEXT                       -- when Pushover alert was sent

Logic:
    * UPSERT via INSERT ... ON CONFLICT(tracking) DO UPDATE
    * Only rows with notified_at IS NULL are considered "new"
    * When a previously-seen package gets a new status, last_updated changes but
      notified_at is NOT cleared (avoid duplicate noise). If you want re-alerts on
      status changes, call clear_notification(tracking) or adjust the logic.
"""
import sqlite3
from typing import Any, Optional

DEFAULT_DB = "packages.db"


def get_conn(db_name: Optional[str] = None) -> sqlite3.Connection:
    """Open a connection with row factory so rows behave like dicts."""
    path = db_name or DEFAULT_DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrency
    return conn


def init_db(db_name: Optional[str] = None) -> None:
    """Create tables and indexes if they don't exist."""
    with get_conn(db_name) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS packages (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking      TEXT UNIQUE NOT NULL,
                description   TEXT,
                price         TEXT,
                status        TEXT,
                last_updated  TEXT,
                created_at    TEXT DEFAULT (datetime('now')),
                notified_at   TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_packages_notified
            ON packages(notified_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_packages_tracking
            ON packages(tracking)
        """)
        conn.commit()


def insert_or_update_package(
    tracking: str,
    description: Optional[str],
    price: Optional[str],
    status: Optional[str],
    last_updated: Optional[str],
    db_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Upsert a package record.

    Returns the row after insert/update so callers can know if it was new
    (id, created_at, etc.).  Does NOT touch notified_at on updates.
    """
    with get_conn(db_name) as conn:
        # Try optimistic insert first using ON CONFLICT upsert.
        cursor = conn.execute(
            """
            INSERT INTO packages (tracking, description, price, status, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tracking) DO UPDATE SET
                description  = excluded.description,
                price          = excluded.price,
                status         = excluded.status,
                last_updated   = excluded.last_updated
            RETURNING *
            """,
            (tracking, description, price, status, last_updated),
        )
        row = cursor.fetchone()
        conn.commit()
        return dict(row)


def get_unsent_packages(db_name: Optional[str] = None) -> list[dict[str, Any]]:
    """Return all packages that have never been notified."""
    with get_conn(db_name) as conn:
        cursor = conn.execute(
            "SELECT * FROM packages WHERE notified_at IS NULL ORDER BY created_at ASC"
        )
        return [dict(row) for row in cursor.fetchall()]


def mark_as_sent(tracking: str, db_name: Optional[str] = None) -> None:
    """Set notified_at = now for the given tracking number."""
    with get_conn(db_name) as conn:
        conn.execute(
            """
            UPDATE packages
            SET notified_at = datetime('now')
            WHERE tracking = ?
            """,
            (tracking,),
        )
        conn.commit()


def clear_notification(tracking: str, db_name: Optional[str] = None) -> None:
    """Reset notified_at so the row becomes unsent again."""
    with get_conn(db_name) as conn:
        conn.execute(
            "UPDATE packages SET notified_at = NULL WHERE tracking = ?",
            (tracking,),
        )
        conn.commit()
