# aws_cargo_2026
A revised, completely rewritten version of the aws_cargo repo.

## Setup

Run in venv and install requirements:

```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

## Scraper / notifier

```bash
# Scrape AWS Cargo and send a consolidated alert
python3 main.py

# Scrape only, do not send alerts or mark as sent
python3 main.py --dry-run

# Retry sending unsent alerts without scraping
python3 main.py --no-scrape

# Use the AWS-specific Pushover token
python3 main.py --aws-token

# Send one alert per package instead of a single consolidated message
python3 main.py --individual
```

## Web interface

Add friendly item names for your tracking numbers:

```bash
python3 web.py
```

Then open `http://<host>:5000`.

Enter tracking items one per line using the format:

```text
<item(s)>: <tracking num>
```

Examples:

```text
Shoes: 1Z999AA10123456784
Books, Kindle: 1Z999AA10123456785
Laptop / Mouse: 1Z999AA10123456786
```

Multiple items can be linked to the same tracking number.

## How it works

1. **Scrape** – Playwright logs in, navigates to the packages page, sets the rows-per-page dropdown to 20, and pulls the table rows.
2. **Store** – SQLite upserts new or changed rows.
3. **Status-change detection** – If a previously seen package gets a new status, it is automatically re-flagged for notification.
4. **Notify** – All pending rows are bundled into a single consolidated message and sent to every configured channel (Pushover and/or Telegram). Friendly item names are included when available.
5. **Mark sent** – Sent rows are marked as notified.
6. **Idempotent** – Re-running does nothing until new packages arrive or an existing package changes status.

## Consolidated alerts

By default `main.py` sends **one message per run** containing all pending packages, so an hourly run with 6 new packages produces one notification instead of six.

If a message exceeds a platform's limit it is split into the smallest number of chunks needed:

- Pushover: 1,024 characters per message
- Telegram: 4,096 characters per message

Use `--individual` if you prefer the old one-alert-per-package behavior.

## Notifications

Alerts are sent through every channel that is configured in `.env`:

- **Pushover**: set `PUSHOVER_USER` and `PUSHOVER_TOKEN` (or `PUSHOVER_TOKEN_AWS`).
- **Telegram**: set `WEBHOOK_HOST`, `WEBHOOK_PATH`, `SEND_API_KEY`, and `TELEGRAM_RECIPIENT`.

If both are configured, each alert is sent to both.
