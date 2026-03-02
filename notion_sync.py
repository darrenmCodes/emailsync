import logging
from datetime import datetime, timezone

from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError

import config

log = logging.getLogger(__name__)


class NotionSync:
    def __init__(self, api_key: str = None, database_id: str = None):
        api_key = api_key or config.NOTION_API_KEY
        database_id = database_id or config.NOTION_DATABASE_ID

        if not api_key:
            raise ValueError("NOTION_API_KEY not set")
        if not database_id:
            raise ValueError("NOTION_DATABASE_ID not set")

        self.client = NotionClient(auth=api_key)
        self.database_id = database_id
        self._page_cache: dict[str, str] = {}  # email -> page_id

    def load_existing_contacts(self):
        """Load all existing contacts from Notion into a local cache for upsert."""
        log.info("Loading existing contacts from Notion...")
        self._page_cache = {}
        start_cursor = None

        while True:
            kwargs = {"database_id": self.database_id, "page_size": 100}
            if start_cursor:
                kwargs["start_cursor"] = start_cursor

            try:
                result = self.client.databases.query(**kwargs)
            except APIResponseError as e:
                log.error("Failed to query Notion database: %s", e)
                raise

            for page in result.get("results", []):
                email_prop = page["properties"].get("Email", {})
                email_val = email_prop.get("email") or ""
                if not email_val:
                    # Fallback for rich_text type
                    rich_text = email_prop.get("rich_text", [])
                    if rich_text:
                        email_val = rich_text[0].get("plain_text", "")
                email_val = email_val.lower().strip()
                if email_val:
                    self._page_cache[email_val] = page["id"]

            if not result.get("has_more"):
                break
            start_cursor = result.get("next_cursor")

        log.info("Loaded %d existing contacts from Notion", len(self._page_cache))

    def sync_contact(self, contact: dict, count_30d: int, count_90d: int):
        """Create or update a contact in Notion."""
        email = contact["email"]
        days_since = self._days_since(contact["last_contact"])

        properties = self._build_properties(
            email=email,
            total_emails=contact["total_emails"],
            first_contact=contact["first_contact"],
            last_contact=contact["last_contact"],
            count_30d=count_30d,
            count_90d=count_90d,
            unique_threads=contact["unique_threads"],
            days_since=days_since,
        )

        page_id = self._page_cache.get(email)
        if page_id:
            self._update_page(page_id, properties, email)
        else:
            self._create_page(properties, email)

    def _build_properties(self, email: str, total_emails: int, first_contact: str,
                          last_contact: str, count_30d: int, count_90d: int,
                          unique_threads: int, days_since: int) -> dict:
        return {
            "Name": {"title": [{"text": {"content": email}}]},
            "Email": {"email": email},
            "Total Emails": {"number": total_emails},
            "First Contact": {"date": {"start": first_contact[:10]}},
            "Last Contact": {"date": {"start": last_contact[:10]}},
            "30 Day Count": {"number": count_30d},
            "90 Day Count": {"number": count_90d},
            "Unique Threads": {"number": unique_threads},
            "Days Since Last Contact": {"number": days_since},
        }

    def _create_page(self, properties: dict, email: str):
        try:
            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
            )
            self._page_cache[email] = page["id"]
            log.info("Created Notion page for %s", email)
        except APIResponseError as e:
            log.error("Failed to create page for %s: %s", email, e)

    def _update_page(self, page_id: str, properties: dict, email: str):
        try:
            self.client.pages.update(page_id=page_id, properties=properties)
            log.debug("Updated Notion page for %s", email)
        except APIResponseError as e:
            log.error("Failed to update page for %s: %s", email, e)

    @staticmethod
    def _days_since(iso_timestamp: str) -> int:
        last = datetime.fromisoformat(iso_timestamp)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - last).days
