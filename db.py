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
        notified_at   TEXT                       -- when alert was last sent

    items
        id            INTEGER PRIMARY KEY AUTOINCREMENT
        name          TEXT NOT NULL              -- friendly item name
        tracking      TEXT NOT NULL              -- associated tracking number
        created_at    TEXT DEFAULT (datetime('now'))
        UNIQUE(name, tracking)

Logic:
    * UPSERT via INSERT ... ON CONFLICT(tracking) DO UPDATE
    * Rows with notified_at IS NULL are considered "pending notification"
    * When a previously-seen package gets a new status, notified_at is cleared
      automatically so the change triggers a fresh alert.
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
            CREATE TABLE IF NOT EXISTS items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                tracking      TEXT NOT NULL,
                created_at    TEXT DEFAULT (datetime('now')),
                UNIQUE(name, tracking)
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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_tracking
            ON items(tracking)
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

    Returns the row after insert/update plus metadata:
        was_new        True if the tracking number did not exist before
        status_changed True if an existing row's status field changed

    If status_changed is True, notified_at is reset to NULL so the change
    triggers a new alert.
    """
    tracking = (tracking or "").strip()
    if not tracking:
        raise ValueError("tracking number cannot be empty")

    with get_conn(db_name) as conn:
        old = conn.execute(
            "SELECT status, notified_at FROM packages WHERE tracking = ?",
            (tracking,),
        ).fetchone()

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

        was_new = old is None
        status_changed = (
            not was_new
            and (old["status"] or "") != (status or "")
        )

        if status_changed:
            conn.execute(
                "UPDATE packages SET notified_at = NULL WHERE tracking = ?",
                (tracking,),
            )
            # Reflect the reset in the returned dict.
            row = conn.execute(
                "SELECT * FROM packages WHERE tracking = ?",
                (tracking,),
            ).fetchone()

        conn.commit()
        result = dict(row)
        result["was_new"] = was_new
        result["status_changed"] = status_changed
        return result


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


# ---------------------------------------------------------------------------
# Items (friendly names for tracking numbers)
# ---------------------------------------------------------------------------


def add_item(name: str, tracking: str, db_name: Optional[str] = None) -> dict[str, Any]:
    """Add a friendly item name linked to a tracking number."""
    name = (name or "").strip()
    tracking = (tracking or "").strip()
    if not name or not tracking:
        raise ValueError("item name and tracking number are required")

    with get_conn(db_name) as conn:
        cursor = conn.execute(
            """
            INSERT INTO items (name, tracking)
            VALUES (?, ?)
            ON CONFLICT(name, tracking) DO UPDATE SET
                tracking = excluded.tracking
            RETURNING *
            """,
            (name, tracking),
        )
        row = cursor.fetchone()
        conn.commit()
        return dict(row)


def delete_item(item_id: int, db_name: Optional[str] = None) -> bool:
    """Delete an item by id. Returns True if a row was removed."""
    with get_conn(db_name) as conn:
        cursor = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_items(db_name: Optional[str] = None) -> list[dict[str, Any]]:
    """Return all item rows ordered by name."""
    with get_conn(db_name) as conn:
        cursor = conn.execute(
            "SELECT * FROM items ORDER BY name COLLATE NOCASE, tracking"
        )
        return [dict(row) for row in cursor.fetchall()]


def get_item_names_for_tracking(
    tracking: str, db_name: Optional[str] = None
) -> list[str]:
    """Return all friendly item names associated with a tracking number."""
    tracking = (tracking or "").strip()
    if not tracking:
        return []

    with get_conn(db_name) as conn:
        cursor = conn.execute(
            """
            SELECT name FROM items
            WHERE tracking = ?
            ORDER BY name COLLATE NOCASE
            """,
            (tracking,),
        )
        return [row["name"] for row in cursor.fetchall()]


def get_packages_with_items(db_name: Optional[str] = None) -> list[dict[str, Any]]:
    """Return all packages annotated with their friendly item names."""
    with get_conn(db_name) as conn:
        pkgs = conn.execute(
            "SELECT * FROM packages ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for pkg in pkgs:
            d = dict(pkg)
            d["item_names"] = get_item_names_for_tracking(d["tracking"], db_name)
            result.append(d)
        return result
