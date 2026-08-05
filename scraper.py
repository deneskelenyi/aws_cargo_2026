"""
AWS Cargo scraper.

Logs in with Playwright (Camoufox if available, otherwise standard Chromium),
navigates to /en/account/packages, extracts the package table rows, and returns
a list of dicts.

Anti-detection notes:
- The site is NOT behind a hard bot wall, so standard Playwright works fine.
- If you have Camoufox installed, set CAMOFOX_URL in .env and we proxy requests
  through it for better stealth. Otherwise, normal Chromium is used.
- We set a realistic viewport and disable automation flags when using vanilla
  Chromium so we don't trip simple JS checks.
"""
import os
import json
from typing import Any, List, Optional
from playwright.sync_api import sync_playwright

LOGIN_URL     = "https://www.awscargo.com/login"
PACKAGES_URL  = "https://www.awscargo.com/en/account/packages"
DEFAULT_TIMEOUT = 15000  # ms
ROWS_PER_PAGE = 25       # try to show this many rows before extracting


def _set_rows_per_page(page: Any, target: int = ROWS_PER_PAGE) -> bool:
    """
    Try to set the packages table rows-per-page dropdown to `target`.

    Supports the AWS Cargo Bootstrap-style select as well as common
    DataTables selectors. Returns True if an option was successfully selected.
    """
    selectors = [
        'select.form-select-sm',
        'select.form-select',
        f'select:has(option[value="{target}"])',
        'select[name$="_length"]',
        '.dataTables_length select',
    ]
    for sel in selectors:
        select = page.locator(sel).first
        try:
            if select.count() == 0:
                continue
            # Try selecting by value first, then by visible label.
            try:
                select.select_option(str(target))
            except Exception:
                select.select_option(label=str(target))
            print(f"[scraper] Set rows per page to {target}.")
            return True
        except Exception:
            continue
    print("[scraper] Rows-per-page dropdown not found; using current page size.")
    return False


def _extract_rows(page: Any) -> List[dict]:
    """Extract package rows from the current page's table."""
    return page.evaluate("""
        () => {
            const trs = document.querySelectorAll('table tbody tr');
            const data = [];
            for (const tr of trs) {
                const cells = tr.querySelectorAll('td');
                if (cells.length < 5) continue;
                data.push({
                    tracking:    cells[0]?.innerText?.trim() || '',
                    description: cells[1]?.innerText?.trim() || '',
                    price:       cells[2]?.innerText?.trim() || '',
                    status:      cells[3]?.innerText?.trim() || '',
                    last_updated: cells[4]?.innerText?.trim() || ''
                });
            }
            return data;
        }
    """)


def _make_browser(p: Any) -> Any:
    """
    Launch browser.

    Priority:
      1. If CAMOFOX_URL is set, connect to that remote Camoufox REST server.
      2. Otherwise launch standard Chromium with stealth-ish args.
    """
    camoufox_url = os.getenv("CAMOFOX_URL", "").strip()
    if camoufox_url:
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{camoufox_url}/start",
                data=b'{"userId":"aws","sessionKey":"scraper"}',
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read())
            ws_url = payload.get("wsUrl") or payload.get("wsEndpoint")
            if ws_url:
                print(f"[scraper] Connecting to Camoufox at {ws_url}")
                return p.chromium.connect_over_cdp(ws_url)
        except Exception as exc:
            print(f"[scraper] Camoufox start failed ({exc}), falling back to Chromium.")

    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
    ]
    return p.chromium.launch(headless=True, args=args)


def scrape_packages(
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> List[dict]:
    """
    Scrape the packages table from AWS Cargo.

    Returns list of dicts with keys:
        tracking, description, price, status, last_updated
    """
    username = username or os.getenv("AWS_USERNAME", "").strip()
    password = password or os.getenv("AWS_PASSWORD", "").strip()
    if not username or not password:
        raise ValueError("AWS_USERNAME and AWS_PASSWORD must be set in .env or passed as args")

    with sync_playwright() as p:
        browser = _make_browser(p)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT)

        print("[scraper] Navigating to login page...")
        page.goto(LOGIN_URL, wait_until="networkidle")

        # Fill credentials.
        page.locator('input[type="email"], input[name="email"], #email, [placeholder*="Email"]').first.fill(username)
        page.locator('input[type="password"], input[name="password"], #password, [placeholder*="Contraseña"], [placeholder*="Password"]').first.fill(password)

        # Click login button and wait for a successful-login indicator.
        page.locator('button[type="submit"], button:has-text("Iniciar sesión"), button:has-text("Log in"), button:has-text("Login")').first.click()

        # Wait up to 10 seconds for the presence of a "Log Out" or "My Account" element
        # which signals we are authenticated regardless of URL changes.
        try:
            page.wait_for_selector('text=Log Out, text=Cerrar Sesión, text=My Account, text=Mi Cuenta', timeout=10000)
            print("[scraper] Logged in successfully.")
        except Exception:
            # Fallback: wait a bit for SPA redirect then check URL.
            page.wait_for_timeout(2000)
            if "/login" in page.url:
                raise RuntimeError("Login failed — still on login page")

        print("[scraper] Navigating to packages page...")
        page.goto(PACKAGES_URL, wait_until="networkidle")

        # Sometimes tables load asynchronously. Wait for either rows or the empty-message cell.
        try:
            page.wait_for_selector("table tbody tr", timeout=DEFAULT_TIMEOUT)
        except Exception:
            page.wait_for_selector("text=No records to display", timeout=5000)
            print("[scraper] No records to display.")
            browser.close()
            return []

        # Try to show more rows per page before extracting (default is often 10).
        if _set_rows_per_page(page):
            # Give the table a moment to reload its data.
            page.wait_for_timeout(1500)
            try:
                page.wait_for_selector("table tbody tr", timeout=DEFAULT_TIMEOUT)
            except Exception:
                pass

        rows = _extract_rows(page)

        browser.close()
        print(f"[scraper] Scraped {len(rows)} packages.")
        return rows
