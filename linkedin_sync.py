"""Sync LinkedIn connections to a Notion database.

Mirrors the cache-then-upsert pattern from notion_sync.py.
Uses LinkedIn URL as the unique key for deduplication.
"""

from __future__ import annotations

import logging

from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError

log = logging.getLogger(__name__)


class LinkedInNotionSync:
    def __init__(self, api_key: str, database_id: str):
        if not api_key:
            raise ValueError("Notion API key not set")
        if not database_id:
            raise ValueError("Notion Database ID not set for LinkedIn")

        self.client = NotionClient(auth=api_key)
        self.database_id = database_id
        self._page_cache: dict[str, str] = {}  # linkedin_url -> page_id

    def load_existing_connections(self):
        """Load all existing connections from Notion into a local cache."""
        log.info("Loading existing LinkedIn connections from Notion...")
        self._page_cache = {}
        start_cursor = None

        while True:
            kwargs = {"database_id": self.database_id, "page_size": 100}
            if start_cursor:
                kwargs["start_cursor"] = start_cursor

            try:
                result = self.client.databases.query(**kwargs)
            except APIResponseError as e:
                log.error("Failed to query LinkedIn Notion database: %s", e)
                raise

            for page in result.get("results", []):
                url_prop = page["properties"].get("LinkedIn URL", {})
                url_val = url_prop.get("url") or ""
                if url_val:
                    self._page_cache[url_val] = page["id"]

            if not result.get("has_more"):
                break
            start_cursor = result.get("next_cursor")

        log.info("Loaded %d existing connections from Notion", len(self._page_cache))

    def sync_connection(self, connection: dict):
        """Create or update a connection in Notion."""
        linkedin_url = connection.get("linkedin_url", "")
        if not linkedin_url:
            log.warning("Skipping connection with no LinkedIn URL: %s", connection)
            return

        first = connection.get("first_name", "")
        last = connection.get("last_name", "")
        full_name = f"{first} {last}".strip() or "Unknown"

        properties = {
            "Name": {"title": [{"text": {"content": full_name}}]},
            "First Name": {"rich_text": [{"text": {"content": first}}]},
            "Last Name": {"rich_text": [{"text": {"content": last}}]},
            "Company": {"rich_text": [{"text": {"content": connection.get("company", "")}}]},
            "Position": {"rich_text": [{"text": {"content": connection.get("position", "")}}]},
            "LinkedIn URL": {"url": linkedin_url or None},
            "Email": {"email": connection.get("email") or None},
        }

        connected_on = connection.get("connected_on")
        if connected_on:
            properties["Connected On"] = {"date": {"start": connected_on[:10]}}

        page_id = self._page_cache.get(linkedin_url)
        if page_id:
            self._update_page(page_id, properties, full_name)
        else:
            self._create_page(properties, full_name, linkedin_url)

    def _create_page(self, properties: dict, name: str, linkedin_url: str):
        try:
            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
            )
            self._page_cache[linkedin_url] = page["id"]
            log.info("Created Notion page for %s", name)
        except APIResponseError as e:
            log.error("Failed to create page for %s: %s", name, e)

    def _update_page(self, page_id: str, properties: dict, name: str):
        try:
            self.client.pages.update(page_id=page_id, properties=properties)
            log.debug("Updated Notion page for %s", name)
        except APIResponseError as e:
            log.error("Failed to update page for %s: %s", name, e)
