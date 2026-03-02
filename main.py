#!/usr/bin/env python3
"""
Gmail → Notion Email Engagement Sync

Syncs Gmail sent-email data into a local SQLite database,
computes engagement metrics per contact, and upserts to Notion.
"""

import sys
import logging
import time
from datetime import datetime, timezone

import config
from database import Database
from gmail_client import GmailClient
from processor import process_message
from notion_sync import NotionSync

log = logging.getLogger(__name__)


def sync_gmail(db: Database, gmail: GmailClient) -> set[str]:
    """Fetch new sent emails from Gmail and store them locally.
    Returns the set of recipient emails affected by this sync."""

    last_sync = db.get_last_sync_timestamp()
    if last_sync:
        log.info("Incremental sync — fetching emails after %s", last_sync)
    else:
        log.info("First run — fetching entire sent mail history")

    message_refs = gmail.fetch_sent_message_ids(after_timestamp=last_sync)
    log.info("Found %d message IDs to process", len(message_refs))

    if not message_refs:
        return set()

    affected_emails: set[str] = set()
    processed = 0
    skipped = 0
    errors = 0
    latest_timestamp = last_sync

    for i, ref in enumerate(message_refs):
        msg_id = ref["id"]

        if db.is_message_processed(msg_id):
            skipped += 1
            continue

        raw = gmail.get_message(msg_id)
        if not raw:
            errors += 1
            continue

        parsed = process_message(raw)
        if not parsed:
            skipped += 1
            continue

        stored = db.store_email(
            message_id=parsed["message_id"],
            thread_id=parsed["thread_id"],
            sent_at=parsed["sent_at"],
            sender=parsed["sender"],
            recipients=parsed["recipients"],
        )

        if stored:
            processed += 1
            for r in parsed["recipients"]:
                affected_emails.add(r["email"])

            # Track the latest timestamp for next incremental sync
            if not latest_timestamp or parsed["sent_at"] > latest_timestamp:
                latest_timestamp = parsed["sent_at"]

        if (i + 1) % 100 == 0:
            log.info("Progress: %d/%d messages checked", i + 1, len(message_refs))

    if latest_timestamp and latest_timestamp != last_sync:
        db.set_last_sync_timestamp(latest_timestamp)

    log.info(
        "Gmail sync complete: %d processed, %d skipped, %d errors",
        processed, skipped, errors,
    )
    return affected_emails


def rebuild_contacts(db: Database, emails: set[str]):
    """Recompute metrics for affected contacts."""
    log.info("Rebuilding metrics for %d contacts", len(emails))
    for email in emails:
        db.rebuild_contact(email)


def sync_to_notion(db: Database, emails: set[str],
                    notion_api_key: str = None, notion_database_id: str = None):
    """Push affected contacts to Notion."""
    api_key = notion_api_key or config.NOTION_API_KEY
    db_id = notion_database_id or config.NOTION_DATABASE_ID

    if not api_key or not db_id:
        log.warning("Notion credentials not configured — skipping Notion sync")
        return

    notion = NotionSync(api_key=api_key, database_id=db_id)
    notion.load_existing_contacts()

    synced = 0
    for email in emails:
        contact = db.get_contact(email)
        if not contact:
            continue

        count_30d = db.get_contact_window_count(email, 30)
        count_90d = db.get_contact_window_count(email, 90)

        notion.sync_contact(contact, count_30d, count_90d)
        synced += 1

        # Pace Notion API calls to stay under rate limits
        if synced % 3 == 0:
            time.sleep(0.35)

    log.info("Notion sync complete: %d contacts synced", synced)


def run_sync(creds=None, db_path=None, progress_callback=None,
             notion_api_key=None, notion_database_id=None):
    """Run the full Gmail → SQLite → Notion sync pipeline.

    Args:
        creds: Optional google.oauth2.credentials.Credentials.
               If None, uses the CLI auth flow (token.json).
        db_path: Optional path to a user-specific SQLite database.
                 If None, uses the default email_crm.db.
        progress_callback: Optional callable(message: str) for status updates.
        notion_api_key: Optional per-user Notion API key.
        notion_database_id: Optional per-user Notion database ID.

    Returns:
        dict with keys: processed, contacts_updated, errors, elapsed
    """
    def _report(msg):
        log.info(msg)
        if progress_callback:
            progress_callback(msg)

    config.setup_logging()
    _report("=== Email Sync Started ===")
    start = time.time()

    db = Database(db_path) if db_path else Database()
    try:
        gmail = GmailClient(creds=creds)

        # Auto-detect user's email if not configured
        if not config.MY_EMAIL_ADDRESSES:
            profile = gmail.get_profile()
            user_email = profile.get("emailAddress", "").lower()
            if user_email:
                config.MY_EMAIL_ADDRESSES.append(user_email)
                _report(f"Auto-detected user email: {user_email}")

        # Step 1: Sync Gmail
        affected_emails = sync_gmail(db, gmail)

        contacts_updated = 0
        if not affected_emails:
            _report("No new emails to process")
        else:
            # Step 2: Rebuild contact metrics
            rebuild_contacts(db, affected_emails)
            contacts_updated = len(affected_emails)

            # Step 3: Sync to Notion
            sync_to_notion(db, affected_emails,
                           notion_api_key=notion_api_key,
                           notion_database_id=notion_database_id)

        elapsed = time.time() - start
        _report(f"=== Sync completed in {elapsed:.1f}s ===")

        return {
            "processed": len(affected_emails),
            "contacts_updated": contacts_updated,
            "errors": 0,
            "elapsed": elapsed,
        }

    except Exception:
        log.exception("Fatal error during sync")
        raise
    finally:
        db.close()


def main():
    try:
        run_sync()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(1)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
