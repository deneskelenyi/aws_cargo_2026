# aws_cargo_2026
A revised, completely rewritten version of the aws_cargo repo. 



Run in venv and install requirements with pip3 -r requirements.txt

To run:
python3 main.py

To run without scraping (resend unsent alerts only)
python3 main.py --no-scrape

To run without actually sending Pushover (test scrape + db only)
python3 main.py --dry-run

How it works: 

1. Scrape - Paywright logs in, navigates to packages page, pulls the table rows.
2. Store - SQLite upserts new or changed rows
3. NMotify - All rows not notified are sent to Pushover
4. Mark sent - send sent rows as sent
5. Idempotent - Re-running doesn't do anythin until new things are sent

   
