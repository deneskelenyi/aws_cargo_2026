"""
Public tracking API client for AWS Cargo.

The public tracking page (https://www.awscargo.com/en/tracking) is backed by a
simple JSON endpoint, no login required:

    GET https://www.awscargo.com/api/tracking/<tracking_number>

Response:
    {"valid": true, "data": [
        {"date": "...", "status": "RECEIVED_ORIGIN", "status_label": "Recibido..."},
        ...
    ]}

An empty "data" array means the number is not registered on the carrier's
public tracking yet (e.g. the vendor created the label but AWS Cargo has not
received it). Events are ordered oldest-first.
"""
from typing import Any, Optional

import requests

TRACKING_API = "https://www.awscargo.com/api/tracking/{}"
REQUEST_TIMEOUT = 15  # seconds


def fetch_tracking(tracking: str) -> Optional[dict[str, Any]]:
    """
    Query the public tracking API for one tracking number.

    Returns None if the number is not registered (empty data / invalid),
    otherwise a dict:
        status        latest status code (e.g. 'IN_TRANSIT_DESTINATION')
        status_label  latest human-readable label
        last_updated  ISO timestamp of the latest event
        events        full event list, oldest first
    """
    tracking = (tracking or "").strip()
    if not tracking:
        return None

    resp = requests.get(TRACKING_API.format(tracking), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    if not payload.get("valid"):
        return None
    events = payload.get("data") or []
    if not events:
        return None

    latest = events[-1]
    return {
        "status": latest.get("status", ""),
        "status_label": latest.get("status_label", ""),
        "last_updated": latest.get("date", ""),
        "events": events,
    }
