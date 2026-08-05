#!/usr/bin/env python3
"""
Debug helper: log in to AWS Cargo, open the packages page, and save the HTML
source plus a screenshot so we can inspect the rows-per-page dropdown and
pagination controls.

Run:
    python debug_page.py

Outputs in the current directory:
    packages_page.html
    packages_page.png
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_PATH = _SCRIPT_DIR / ".env"
if _ENV_PATH.is_file():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    load_dotenv()

LOGIN_URL = "https://www.awscargo.com/login"
PACKAGES_URL = "https://www.awscargo.com/en/account/packages"


def main() -> None:
    username = os.getenv("AWS_USERNAME", "").strip()
    password = os.getenv("AWS_PASSWORD", "").strip()
    if not username or not password:
        raise ValueError("AWS_USERNAME and AWS_PASSWORD must be set in .env")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        print("[debug] Logging in...")
        page.goto(LOGIN_URL, wait_until="networkidle")
        page.locator('input[type="email"], input[name="email"], #email, [placeholder*="Email"]').first.fill(username)
        page.locator('input[type="password"], input[name="password"], #password, [placeholder*="Contraseña"], [placeholder*="Password"]').first.fill(password)
        page.locator('button[type="submit"], button:has-text("Iniciar sesión"), button:has-text("Log in"), button:has-text("Login")').first.click()

        try:
            page.wait_for_selector('text=Log Out, text=Cerrar Sesión, text=My Account, text=Mi Cuenta', timeout=10000)
            print("[debug] Logged in.")
        except Exception:
            page.wait_for_timeout(2000)
            if "/login" in page.url:
                raise RuntimeError("Login failed — still on login page")

        print("[debug] Navigating to packages page...")
        page.goto(PACKAGES_URL, wait_until="networkidle")
        page.wait_for_selector("table tbody tr", timeout=15000)
        page.wait_for_timeout(2000)  # let any JS widgets settle

        html_path = _SCRIPT_DIR / "packages_page.html"
        png_path = _SCRIPT_DIR / "packages_page.png"
        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)

        print(f"[debug] Saved {html_path}")
        print(f"[debug] Saved {png_path}")

        # Print a few selectors that might be useful.
        print("\n[debug] Selectors found on the page:")
        counts = page.evaluate("""
            () => ({
                select: document.querySelectorAll('select').length,
                dataTables_length: document.querySelectorAll('.dataTables_length').length,
                pagination: document.querySelectorAll('.pagination, .paginate_button, [class*="page"]').length,
                next_buttons: Array.from(document.querySelectorAll('a, button')).filter(el => /next|siguiente|>/i.test(el.innerText)).length
            })
        """)
        for k, v in counts.items():
            print(f"  {k}: {v}")

        browser.close()


if __name__ == "__main__":
    main()
