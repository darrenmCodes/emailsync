"""Streamlit dashboard for Gmail → Notion email engagement sync.

Each user signs in with their own Google account.
Their Gmail data is stored in a separate database so
nobody sees anyone else's contacts.
"""

from __future__ import annotations

import os
import streamlit as st
import pandas as pd
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

import config
from database import Database

st.set_page_config(page_title="Email Sync", layout="wide")

# ── Per-user data dirs ───────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TOKENS_DIR = os.path.join(DATA_DIR, "tokens")
DBS_DIR = os.path.join(DATA_DIR, "dbs")

for _d in (DATA_DIR, TOKENS_DIR, DBS_DIR):
    os.makedirs(_d, exist_ok=True)


def _safe_filename(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")


def _token_path(email: str) -> str:
    return os.path.join(TOKENS_DIR, f"{_safe_filename(email)}.json")


def _db_path(email: str) -> str:
    return os.path.join(DBS_DIR, f"{_safe_filename(email)}.db")


# ── Token helpers ────────────────────────────────────────────────────────────

def _save_token(email: str, creds: Credentials):
    with open(_token_path(email), "w") as f:
        f.write(creds.to_json())


def _load_token(email: str) -> Credentials | None:
    path = _token_path(email)
    if not os.path.exists(path):
        return None
    try:
        creds = Credentials.from_authorized_user_file(path, config.GMAIL_SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token(email, creds)
            return creds
    except Exception:
        pass
    return None


def _get_redirect_uri() -> str:
    return os.environ.get("REDIRECT_URI", "http://localhost:8501")


def _get_user_email(creds: Credentials) -> str:
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "unknown").lower()


# ── Handle OAuth callback (Google redirects back with ?code=...) ─────────────

params = st.query_params

if "code" in params and "user_email" not in st.session_state:
    try:
        flow = Flow.from_client_secrets_file(
            config.GOOGLE_CREDENTIALS_FILE,
            scopes=config.GMAIL_SCOPES,
            redirect_uri=_get_redirect_uri(),
        )
        flow.fetch_token(code=params["code"])
        creds = flow.credentials
        email = _get_user_email(creds)
        _save_token(email, creds)
        st.session_state["user_email"] = email
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Sign-in failed: {e}")
        st.query_params.clear()
        st.stop()

# ── Login page ───────────────────────────────────────────────────────────────

if "user_email" not in st.session_state:
    st.title("Email Engagement Sync")
    st.write("Sign in with your Google account to sync your email engagement data to Notion.")

    if not os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
        st.error(
            f"Missing `{config.GOOGLE_CREDENTIALS_FILE}`. "
            "Download it from Google Cloud Console."
        )
        st.stop()

    flow = Flow.from_client_secrets_file(
        config.GOOGLE_CREDENTIALS_FILE,
        scopes=config.GMAIL_SCOPES,
        redirect_uri=_get_redirect_uri(),
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    st.link_button("Sign in with Google", auth_url, type="primary")
    st.stop()

# ── Logged in ────────────────────────────────────────────────────────────────

user_email = st.session_state["user_email"]
user_creds = _load_token(user_email)
user_db = _db_path(user_email)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(f"**{user_email}**")
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.header("Sync")

    db = Database(user_db)
    last_sync = db.get_last_sync_timestamp()
    if last_sync:
        st.caption(f"Last sync: {last_sync}")
    else:
        st.caption("Never synced")

    if not user_creds:
        st.warning("Gmail token expired. Log out and sign in again.")
    elif st.button("Sync Now", type="primary"):
        notion_key = db.get_meta("notion_api_key") or ""
        notion_db = db.get_meta("notion_database_id") or ""
        with st.spinner("Running sync..."):
            try:
                from main import run_sync
                result = run_sync(
                    creds=user_creds,
                    db_path=user_db,
                    notion_api_key=notion_key or None,
                    notion_database_id=notion_db or None,
                )
                st.success(
                    f"Done — {result['processed']} emails, "
                    f"{result['contacts_updated']} contacts updated "
                    f"({result['elapsed']:.1f}s)"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")

    st.divider()
    st.header("Filters")
    search_query = st.text_input("Search by email", placeholder="e.g. alice@")
    days_range = st.slider("Days since last contact", 0, 365, (0, 365))

    # ── Notion settings ──────────────────────────────────────────────────
    st.divider()
    with st.expander("Notion Settings"):
        saved_key = db.get_meta("notion_api_key") or ""
        saved_db_id = db.get_meta("notion_database_id") or ""

        notion_api_key = st.text_input(
            "Notion API Key",
            value=saved_key,
            type="password",
            help="From notion.so/my-integrations",
        )
        notion_database_id = st.text_input(
            "Notion Database ID",
            value=saved_db_id,
            help="The ID from your Notion database URL",
        )

        if st.button("Save Notion Settings"):
            db.set_meta("notion_api_key", notion_api_key.strip())
            db.set_meta("notion_database_id", notion_database_id.strip())
            st.success("Saved!")

# ── Load data ────────────────────────────────────────────────────────────────

contacts = db.get_all_contacts()
now = datetime.now(timezone.utc)

rows = []
for c in contacts:
    last_dt = datetime.fromisoformat(c["last_contact"]) if c["last_contact"] else None
    days_since = (now - last_dt).days if last_dt else None

    rows.append({
        "Email": c["email"],
        "Name": c.get("display_name") or "",
        "Total Emails": c["total_emails"],
        "Threads": c["unique_threads"],
        "First Contact": (c["first_contact"] or "")[:10],
        "Last Contact": (c["last_contact"] or "")[:10],
        "30d Count": db.get_contact_window_count(c["email"], 30),
        "90d Count": db.get_contact_window_count(c["email"], 90),
        "Days Since Last": days_since,
    })

db.close()

df = pd.DataFrame(rows) if rows else pd.DataFrame(
    columns=["Email", "Name", "Total Emails", "Threads",
             "First Contact", "Last Contact", "30d Count",
             "90d Count", "Days Since Last"]
)

# ── Apply filters ────────────────────────────────────────────────────────────

if search_query:
    df = df[df["Email"].str.contains(search_query, case=False, na=False)]

if not df.empty and "Days Since Last" in df.columns:
    mask = df["Days Since Last"].notna()
    df = df[
        ~mask
        | ((df["Days Since Last"] >= days_range[0]) & (df["Days Since Last"] <= days_range[1]))
    ]

# ── Summary metrics ──────────────────────────────────────────────────────────

st.title("Email Engagement Dashboard")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Contacts", len(df))
col2.metric("Total Emails Sent", int(df["Total Emails"].sum()) if not df.empty else 0)

if not df.empty and len(df) > 0:
    most_contacted = df.sort_values("Total Emails", ascending=False).iloc[0]
    col3.metric("Most Contacted", most_contacted["Email"])

    stale = df[df["Days Since Last"].notna() & (df["Days Since Last"] > 30)]
    col4.metric("Going Stale (>30d)", len(stale))
else:
    col3.metric("Most Contacted", "—")
    col4.metric("Going Stale (>30d)", 0)

# ── Contact table ────────────────────────────────────────────────────────────

st.subheader(f"Contacts ({len(df)})")
st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Total Emails": st.column_config.NumberColumn(format="%d"),
        "Threads": st.column_config.NumberColumn(format="%d"),
        "30d Count": st.column_config.NumberColumn("30-Day", format="%d"),
        "90d Count": st.column_config.NumberColumn("90-Day", format="%d"),
        "Days Since Last": st.column_config.NumberColumn("Days Silent", format="%d"),
    },
)
