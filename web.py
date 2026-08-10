#!/usr/bin/env python3
"""
Flask web interface for managing AWS Cargo tracking items.

Run with:
    python web.py

Environment (loaded from .env):
    DB_NAME      Optional custom SQLite path (default: packages.db)
    FLASK_PORT   Port to bind (default: 5000)

Input format:
    <item(s)>: <tracking num>

Examples:
    Shoes: 1Z999AA10123456784
    Books, Kindle: 1Z999AA10123456785
    Laptop / Mouse: 1Z999AA10123456786
"""
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import Flask, redirect, render_template_string, request, url_for

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_PATH = _SCRIPT_DIR / ".env"
if _ENV_PATH.is_file():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    load_dotenv()

from db import (
    add_item,
    delete_item,
    get_items,
    get_packages_with_items,
    init_db,
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")
DB_NAME = os.getenv("DB_NAME", "").strip() or str(_SCRIPT_DIR / "packages.db")

# Ensure the database schema exists before the first request.
init_db(DB_NAME)


HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AWS Cargo Tracker</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
    h1, h2 { margin-top: 2rem; }
    textarea { width: 100%; min-height: 120px; font-family: monospace; font-size: 1rem; padding: 0.5rem; }
    button { padding: 0.6rem 1.2rem; font-size: 1rem; cursor: pointer; }
    .success { color: #2e7d32; background: #e8f5e9; padding: 0.75rem; border-radius: 4px; }
    .error { color: #c62828; background: #ffebee; padding: 0.75rem; border-radius: 4px; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #ccc; }
    th { font-weight: 600; }
    th.sortable { cursor: pointer; user-select: none; }
    th.sortable:hover { background: #f0f0f0; }
    th .arrow { margin-left: 0.25rem; }
    .muted { color: #777; }
    .badge { display: inline-block; background: #e0e0e0; border-radius: 999px; padding: 0.15rem 0.5rem; margin: 0.1rem; font-size: 0.85rem; }
    form.inline { display: inline; }
    .filters { display: flex; gap: 1rem; flex-wrap: wrap; align-items: end; margin-top: 1rem; }
    .filters label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
    .filters input { padding: 0.4rem; font-size: 1rem; min-width: 200px; }
    .filters button { padding: 0.5rem 1rem; }
    .filter-summary { margin-top: 0.5rem; font-size: 0.9rem; }
  </style>
</head>
<body>
  <h1>AWS Cargo Tracker</h1>

  <h2>Add tracking items</h2>
  <p>Enter one or more lines in <code>&lt;item(s)&gt;: &lt;tracking num&gt;</code> format.</p>
  <form method="post" action="{{ url_for('index') }}">
    <textarea name="items_text" placeholder="Shoes: 1Z999AA10123456784\nBooks, Kindle: 1Z999AA10123456785" required>{{ request.form.get('items_text', '') }}</textarea>
    <br><br>
    <button type="submit">Save items</button>
  </form>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <p class="{{ category }}">{{ message }}</p>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <h2>Linked items</h2>

  <form method="get" action="{{ url_for('index') }}" class="filters">
    {% if show_all %}<input type="hidden" name="show_all" value="1">{% endif %}
    {% if sort_by %}<input type="hidden" name="sort_items_by" value="{{ sort_by }}">{% endif %}
    {% if sort_dir %}<input type="hidden" name="sort_items_dir" value="{{ sort_dir }}">{% endif %}
    <div>
      <label for="filter_tracking">Tracking</label>
      <input list="tracking_options" id="filter_tracking" name="filter_tracking" value="{{ filter_tracking }}" placeholder="Filter tracking...">
      <datalist id="tracking_options">
        {% for t in all_trackings %}<option value="{{ t }}">{% endfor %}
      </datalist>
    </div>
    <div>
      <label for="filter_name">Item name</label>
      <input list="name_options" id="filter_name" name="filter_name" value="{{ filter_name }}" placeholder="Filter item name...">
      <datalist id="name_options">
        {% for n in all_names %}<option value="{{ n }}">{% endfor %}
      </datalist>
    </div>
    <button type="submit">Filter</button>
    <a href="{{ url_for('index', **base_params) }}">Clear filters</a>
  </form>

  {% if items %}
    <p class="filter-summary">Showing {{ items|length }} item(s).</p>
    <table>
      <thead>
        <tr>
          <th class="sortable" onclick="window.location='{{ sort_url('item') }}'">Item{{ sort_arrow('item') }}</th>
          <th class="sortable" onclick="window.location='{{ sort_url('tracking') }}'">Tracking{{ sort_arrow('tracking') }}</th>
          <th class="sortable" onclick="window.location='{{ sort_url('added') }}'">Added{{ sort_arrow('added') }}</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for item in items %}
        <tr>
          <td>{{ item.name }}</td>
          <td><code>{{ item.tracking }}</code></td>
          <td class="muted">{{ item.created_at }}</td>
          <td>
            <form class="inline" method="post" action="{{ url_for('delete_item_route', item_id=item.id) }}">
              <button type="submit" onclick="return confirm('Delete this item?')">Delete</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="muted">No items linked yet{% if filter_tracking or filter_name %} matching your filters{% endif %}.</p>
  {% endif %}

  <h2>Packages</h2>
  {% if hidden_count > 0 %}
    <p class="muted">
      {{ hidden_count }} delivered package(s) older than 1 week hidden.
      <a href="{{ url_for('index', show_all=1) if not show_all else url_for('index') }}">
        {{ "Hide past items" if show_all else "See past items" }}
      </a>
    </p>
  {% endif %}
  {% if packages %}
    <table>
      <thead>
        <tr><th>Tracking</th><th>Status</th><th>Price</th><th>Description</th><th>Items</th><th>Last updated</th></tr>
      </thead>
      <tbody>
        {% for pkg in packages %}
        <tr>
          <td><code>{{ pkg.tracking }}</code></td>
          <td>{{ pkg.status or '-' }}</td>
          <td>{{ pkg.price or '-' }}</td>
          <td>{{ pkg.description or '-' }}</td>
          <td>
            {% if pkg.item_names %}
              {% for name in pkg.item_names %}<span class="badge">{{ name }}</span>{% endfor %}
            {% else %}
              <span class="muted">(none)</span>
            {% endif %}
          </td>
          <td class="muted">{{ pkg.last_updated or '-' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="muted">No packages in the database yet. Run <code>python main.py</code> to scrape.</p>
  {% endif %}
</body>
</html>
"""


def _split_item_names(raw: str) -> list[str]:
    """Split the left-hand side of 'items: tracking' into individual names."""
    return [name.strip() for name in re.split(r"[,/&+]", raw) if name.strip()]


def _parse_items_text(text: str) -> list[tuple[str, str]]:
    """
    Parse multi-line text in '<item(s)>: <tracking num>' format.

    Returns a list of (item_name, tracking) tuples.
    """
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        tracking = right.strip()
        if not tracking:
            continue
        for name in _split_item_names(left):
            results.append((name, tracking))
    return results


def _is_old_delivered(pkg: dict) -> bool:
    """Return True if a package is Delivered and older than one week."""
    status = (pkg.get("status") or "").lower()
    if status != "delivered":
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    last_updated = (pkg.get("last_updated") or "").strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(last_updated, fmt).replace(tzinfo=timezone.utc) < cutoff
        except ValueError:
            continue

    try:
        created = datetime.fromisoformat(pkg.get("created_at") or "")
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created < cutoff
    except Exception:
        return False


def _package_sort_key(pkg: dict):
    """
    Sort active statuses ('On the Way', 'Ready for Pickup') first,
    then everything else by date ascending (oldest first).
    """
    status = (pkg.get("status") or "").lower()
    active = status in ("on the way", "ready for pickup")

    date_str = (pkg.get("last_updated") or "").strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    else:
        try:
            dt = datetime.fromisoformat(pkg.get("created_at") or "")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.max.replace(tzinfo=timezone.utc)

    # active first (False < True), then date ascending
    return (not active, dt)


def _filter_items(
    items: list[dict],
    filter_tracking: str,
    filter_name: str,
) -> list[dict]:
    """Return items whose tracking and/or name contain the filter substrings."""
    ft = filter_tracking.lower().strip()
    fn = filter_name.lower().strip()
    result = items
    if ft:
        result = [it for it in result if ft in it["tracking"].lower()]
    if fn:
        result = [it for it in result if fn in it["name"].lower()]
    return result


def _sort_items(
    items: list[dict],
    sort_by: str,
    sort_dir: str,
) -> list[dict]:
    """Sort items by the selected column and direction."""
    reverse = sort_dir == "desc"
    if sort_by == "item":
        key = lambda it: it["name"].lower()
    elif sort_by == "tracking":
        key = lambda it: it["tracking"].lower()
    elif sort_by == "added":
        key = lambda it: it["created_at"] or ""
    else:
        # Default: item name ascending
        sort_by = "item"
        key = lambda it: it["name"].lower()
    return sorted(items, key=key, reverse=reverse)


def _build_sort_url(
    base_params: dict,
    current_by: str,
    current_dir: str,
    column: str,
) -> str:
    """Toggle sort direction when clicking the same column."""
    params = dict(base_params)
    if current_by == column:
        params["sort_items_dir"] = "desc" if current_dir == "asc" else "asc"
    else:
        params["sort_items_by"] = column
        params["sort_items_dir"] = "asc"
    return f"{url_for('index')}?{urlencode(params)}"


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        items_text = request.form.get("items_text", "")
        pairs = _parse_items_text(items_text)
        added = 0
        skipped = 0
        for name, tracking in pairs:
            try:
                add_item(name, tracking, db_name=DB_NAME)
                added += 1
            except Exception:
                skipped += 1
        if added:
            msg = f"Added {added} item(s)."
            if skipped:
                msg += f" {skipped} duplicate or invalid line(s) skipped."
            from flask import flash
            flash(msg, "success")
        else:
            from flask import flash
            flash("No valid items found. Use the format '&lt;items&gt;: &lt;tracking&gt;'.", "error")
        return redirect(url_for("index"))

    # Read query params.
    show_all = request.args.get("show_all") == "1"
    filter_tracking = (request.args.get("filter_tracking") or "").strip()
    filter_name = (request.args.get("filter_name") or "").strip()
    sort_by = request.args.get("sort_items_by", "item").strip() or "item"
    sort_dir = request.args.get("sort_items_dir", "asc").strip() or "asc"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    # Packages section.
    packages = get_packages_with_items(db_name=DB_NAME)
    hidden_count = sum(1 for p in packages if _is_old_delivered(p))
    if not show_all:
        packages = [p for p in packages if not _is_old_delivered(p)]
    packages.sort(key=_package_sort_key)

    # Items section.
    all_items = get_items(db_name=DB_NAME)
    filtered_items = _filter_items(all_items, filter_tracking, filter_name)
    filtered_items = _sort_items(filtered_items, sort_by, sort_dir)

    # Base params for links (preserve show_all, omit filters/sort for clear link).
    base_params = {}
    if show_all:
        base_params["show_all"] = "1"

    # Params for sort links (preserve filters and show_all).
    sort_base_params = {}
    if show_all:
        sort_base_params["show_all"] = "1"
    if filter_tracking:
        sort_base_params["filter_tracking"] = filter_tracking
    if filter_name:
        sort_base_params["filter_name"] = filter_name

    def sort_url(column: str) -> str:
        return _build_sort_url(sort_base_params, sort_by, sort_dir, column)

    def sort_arrow(column: str) -> str:
        if sort_by == column:
            return " ▲" if sort_dir == "asc" else " ▼"
        return ""

    return render_template_string(
        HTML,
        items=filtered_items,
        all_items=all_items,
        all_trackings=sorted({it["tracking"] for it in all_items}),
        all_names=sorted({it["name"] for it in all_items}),
        packages=packages,
        hidden_count=hidden_count,
        show_all=show_all,
        filter_tracking=filter_tracking,
        filter_name=filter_name,
        sort_by=sort_by,
        sort_dir=sort_dir,
        base_params=base_params,
        sort_url=sort_url,
        sort_arrow=sort_arrow,
    )


@app.route("/delete/<int:item_id>", methods=["POST"])
def delete_item_route(item_id: int):
    delete_item(item_id, db_name=DB_NAME)
    from flask import flash
    flash("Item deleted.", "success")
    return redirect(url_for("index"))


def main() -> None:
    init_db(DB_NAME)
    port = int(os.getenv("FLASK_PORT", "5000").strip() or "5000")
    # Bind to all interfaces so it is reachable on the LAN.
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
