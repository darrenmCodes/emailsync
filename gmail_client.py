from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

log = logging.getLogger(__name__)


class GmailClient:
    def __init__(self, creds=None):
        self.creds = creds if creds else self._authenticate()
        self.service = build("gmail", "v1", credentials=self.creds)
        self.user_id = "me"

    def _authenticate(self) -> Credentials:
        creds = None
        if os.path.exists(config.GOOGLE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(
                config.GOOGLE_TOKEN_FILE, config.GMAIL_SCOPES
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                log.info("Refreshing expired Google token")
                creds.refresh(Request())
            else:
                if not os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
                    raise FileNotFoundError(
                        f"Missing {config.GOOGLE_CREDENTIALS_FILE}. "
                        "Download it from Google Cloud Console."
                    )
                log.info("Starting OAuth flow — a browser window will open")
                flow = InstalledAppFlow.from_client_secrets_file(
                    config.GOOGLE_CREDENTIALS_FILE, config.GMAIL_SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(config.GOOGLE_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            log.info("Token saved to %s", config.GOOGLE_TOKEN_FILE)

        return creds

    def get_profile(self) -> dict:
        return self.service.users().getProfile(userId=self.user_id).execute()

    def fetch_sent_message_ids(self, after_timestamp: str | None = None) -> list[dict]:
        """Fetch all sent message IDs, optionally after a timestamp (ISO format).
        Returns list of {'id': ..., 'threadId': ...}."""
        query = "in:sent"
        if after_timestamp:
            # Gmail uses epoch seconds for after: filter
            dt = datetime.fromisoformat(after_timestamp)
            epoch = int(dt.timestamp())
            query += f" after:{epoch}"

        all_messages = []
        page_token = None
        page_num = 0

        while True:
            page_num += 1
            try:
                result = self.service.users().messages().list(
                    userId=self.user_id,
                    q=query,
                    maxResults=config.GMAIL_BATCH_SIZE,
                    pageToken=page_token,
                ).execute()
            except HttpError as e:
                if e.resp.status == 429:
                    log.warning("Rate limited, backing off 10s...")
                    time.sleep(10)
                    continue
                raise

            messages = result.get("messages", [])
            all_messages.extend(messages)
            log.info("Page %d: fetched %d message IDs (total: %d)",
                     page_num, len(messages), len(all_messages))

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return all_messages

    def get_message(self, message_id: str) -> dict | None:
        """Fetch a single message's metadata. Returns parsed dict or None on error."""
        for attempt in range(3):
            try:
                msg = self.service.users().messages().get(
                    userId=self.user_id,
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["From", "To", "Cc", "Bcc"],
                ).execute()
                return self._parse_message(msg)
            except HttpError as e:
                if e.resp.status == 429:
                    wait = 2 ** attempt * 5
                    log.warning("Rate limited on message %s, waiting %ds", message_id, wait)
                    time.sleep(wait)
                    continue
                if e.resp.status == 404:
                    log.warning("Message %s not found, skipping", message_id)
                    return None
                raise
        log.error("Failed to fetch message %s after retries", message_id)
        return None

    def _parse_message(self, raw: dict) -> dict:
        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
        internal_date_ms = int(raw.get("internalDate", "0"))
        sent_at = datetime.fromtimestamp(
            internal_date_ms / 1000, tz=timezone.utc
        ).isoformat()

        return {
            "message_id": raw["id"],
            "thread_id": raw["threadId"],
            "sent_at": sent_at,
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "bcc": headers.get("bcc", ""),
        }
