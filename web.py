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
from pathlib import Path

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
DB_NAME = os.getenv("DB_NAME", "packages.db").strip() or "packages.db"

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
    .muted { color: #777; }
    .badge { display: inline-block; background: #e0e0e0; border-radius: 999px; padding: 0.15rem 0.5rem; margin: 0.1rem; font-size: 0.85rem; }
    form.inline { display: inline; }
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
  {% if items %}
    <table>
      <thead><tr><th>Item</th><th>Tracking</th><th>Added</th><th></th></tr></thead>
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
    <p class="muted">No items linked yet.</p>
  {% endif %}

  <h2>Packages</h2>
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

    return render_template_string(
        HTML,
        items=get_items(db_name=DB_NAME),
        packages=get_packages_with_items(db_name=DB_NAME),
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
