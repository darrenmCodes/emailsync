from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

DB_FILE = "email_sync.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    email           TEXT PRIMARY KEY,
    display_name    TEXT,
    total_emails    INTEGER DEFAULT 0,
    first_contact   TEXT,
    last_contact    TEXT,
    unique_threads  INTEGER DEFAULT 0,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS emails_processed (
    message_id  TEXT PRIMARY KEY,
    thread_id   TEXT,
    sent_at     TEXT,
    sender      TEXT
);

CREATE TABLE IF NOT EXISTS email_recipients (
    message_id  TEXT,
    email       TEXT,
    field       TEXT,  -- 'to', 'cc', 'bcc'
    PRIMARY KEY (message_id, email),
    FOREIGN KEY (message_id) REFERENCES emails_processed(message_id)
);

CREATE TABLE IF NOT EXISTS metadata (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

CREATE TABLE IF NOT EXISTS linkedin_connections (
    linkedin_url    TEXT PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    company         TEXT,
    position        TEXT,
    connected_on    TEXT,
    updated_at      TEXT
);
"""


class Database:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        log.info("Database schema initialized")

    def close(self):
        self.conn.close()

    # -- Metadata --

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def get_last_sync_timestamp(self) -> str | None:
        return self.get_meta("last_sync_timestamp")

    def set_last_sync_timestamp(self, ts: str):
        self.set_meta("last_sync_timestamp", ts)

    def get_last_history_id(self) -> str | None:
        return self.get_meta("last_history_id")

    def set_last_history_id(self, hid: str):
        self.set_meta("last_history_id", hid)

    # -- Email processing --

    def is_message_processed(self, message_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM emails_processed WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row is not None

    def store_email(self, message_id: str, thread_id: str, sent_at: str, sender: str,
                    recipients: list[dict]):
        """Store a processed email and its recipients. Skips if already exists."""
        if self.is_message_processed(message_id):
            return False

        self.conn.execute(
            "INSERT INTO emails_processed (message_id, thread_id, sent_at, sender) "
            "VALUES (?, ?, ?, ?)",
            (message_id, thread_id, sent_at, sender),
        )
        for r in recipients:
            self.conn.execute(
                "INSERT OR IGNORE INTO email_recipients (message_id, email, field) "
                "VALUES (?, ?, ?)",
                (message_id, r["email"], r["field"]),
            )
        self.conn.commit()
        return True

    # -- Contact metrics --

    def rebuild_contact(self, email: str):
        """Recompute all metrics for a single contact from raw email data."""
        rows = self.conn.execute(
            """
            SELECT ep.message_id, ep.thread_id, ep.sent_at
            FROM email_recipients er
            JOIN emails_processed ep ON er.message_id = ep.message_id
            WHERE er.email = ?
            ORDER BY ep.sent_at
            """,
            (email,),
        ).fetchall()

        if not rows:
            self.conn.execute("DELETE FROM contacts WHERE email = ?", (email,))
            self.conn.commit()
            return

        total = len(rows)
        first_contact = rows[0]["sent_at"]
        last_contact = rows[-1]["sent_at"]
        threads = len(set(r["thread_id"] for r in rows))

        self.conn.execute(
            """
            INSERT INTO contacts (email, total_emails, first_contact, last_contact,
                                  unique_threads, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                total_emails = excluded.total_emails,
                first_contact = excluded.first_contact,
                last_contact = excluded.last_contact,
                unique_threads = excluded.unique_threads,
                updated_at = excluded.updated_at
            """,
            (email, total, first_contact, last_contact, threads,
             datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_contact(self, email: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_contacts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM contacts ORDER BY total_emails DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_contact_window_count(self, email: str, days: int) -> int:
        """Count emails sent to this contact in the last N days."""
        cutoff = datetime.now(timezone.utc).isoformat()[:10]  # today
        row = self.conn.execute(
            """
            SELECT COUNT(*) as cnt
            FROM email_recipients er
            JOIN emails_processed ep ON er.message_id = ep.message_id
            WHERE er.email = ?
              AND ep.sent_at >= date(?, '-' || ? || ' days')
            """,
            (email, cutoff, days),
        ).fetchone()
        return row["cnt"] if row else 0

    # -- LinkedIn connections --

    def store_linkedin_connection(
        self,
        linkedin_url: str,
        first_name: str = "",
        last_name: str = "",
        email: str = "",
        company: str = "",
        position: str = "",
        connected_on: str = "",
    ):
        """Upsert a LinkedIn connection."""
        self.conn.execute(
            """
            INSERT INTO linkedin_connections
                (linkedin_url, first_name, last_name, email, company, position, connected_on, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(linkedin_url) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                email = excluded.email,
                company = excluded.company,
                position = excluded.position,
                connected_on = excluded.connected_on,
                updated_at = excluded.updated_at
            """,
            (linkedin_url, first_name, last_name, email, company, position,
             connected_on, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_all_linkedin_connections(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM linkedin_connections ORDER BY connected_on DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_linkedin_connection_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM linkedin_connections"
        ).fetchone()
        return row["cnt"] if row else 0

    # -- Email metrics --

    def get_affected_emails(self, since_timestamp: str | None = None) -> set[str]:
        """Get all unique recipient emails from emails processed since a timestamp."""
        if since_timestamp:
            rows = self.conn.execute(
                """
                SELECT DISTINCT er.email
                FROM email_recipients er
                JOIN emails_processed ep ON er.message_id = ep.message_id
                WHERE ep.sent_at >= ?
                """,
                (since_timestamp,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT DISTINCT email FROM email_recipients"
            ).fetchall()
        return {r["email"] for r in rows}
