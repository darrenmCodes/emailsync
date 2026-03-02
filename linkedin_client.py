"""LinkedIn OAuth + Member Data Portability API client.

Uses the DMA-mandated Member Data Portability API (self-serve variant)
to fetch a user's LinkedIn connections via the Snapshot API.
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
SNAPSHOT_URL = "https://api.linkedin.com/rest/memberSnapshotData"
SCOPE = "r_dma_portability_self_serve"
LINKEDIN_VERSION = "202312"


def get_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the LinkedIn OAuth authorization URL."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
    }
    qs = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{AUTH_URL}?{qs}"


def exchange_code(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> dict:
    """Exchange an authorization code for an access token."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_connections(access_token: str) -> list[dict]:
    """Fetch all connections via the Member Data Portability Snapshot API.

    Paginates through the CONNECTIONS domain and returns a list of
    connection dicts with fields like firstName, lastName, company, etc.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }

    all_connections = []
    start = 0
    count = 100

    while True:
        resp = requests.get(
            SNAPSHOT_URL,
            params={
                "q": "criteria",
                "domain": "CONNECTIONS",
                "start": start,
                "count": count,
            },
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        elements = data.get("elements", [])
        if not elements:
            break

        all_connections.extend(elements)
        log.info(
            "Fetched %d connections (total: %d)", len(elements), len(all_connections)
        )

        # Check for pagination
        paging = data.get("paging", {})
        total = paging.get("total", 0)
        start += len(elements)
        if start >= total or len(elements) < count:
            break

    log.info("Total connections fetched: %d", len(all_connections))
    return all_connections
