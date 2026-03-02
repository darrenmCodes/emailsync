"""Streamlit dashboard for Gmail → Notion email engagement sync
and LinkedIn connections sync.

Each user signs in with their own Google account.
Their Gmail data is stored in a separate database so
nobody sees anyone else's contacts.
"""

from __future__ import annotations

import json
import os
import secrets
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


def _linkedin_token_path(email: str) -> str:
    return os.path.join(TOKENS_DIR, f"{_safe_filename(email)}_linkedin.json")


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


def _save_linkedin_token(email: str, token_data: dict):
    with open(_linkedin_token_path(email), "w") as f:
        json.dump(token_data, f)


def _load_linkedin_token(email: str) -> dict | None:
    path = _linkedin_token_path(email)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _get_redirect_uri() -> str:
    return os.environ.get("REDIRECT_URI", "http://localhost:8501")


def _get_user_email(creds: Credentials) -> str:
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "unknown").lower()


# ── Handle OAuth callbacks ────────────────────────────────────────────────────

params = st.query_params

# LinkedIn OAuth callback
if "code" in params and params.get("state", "").startswith("linkedin_"):
    if "user_email" in st.session_state:
        expected_state = st.session_state.get("linkedin_state", "")
        if params["state"] == expected_state:
            try:
                from linkedin_client import exchange_code
                _cb_db = Database(_db_path(st.session_state["user_email"]))
                _cb_li_id = _cb_db.get_meta("linkedin_client_id") or getattr(config, "LINKEDIN_CLIENT_ID", "") or ""
                _cb_li_secret = _cb_db.get_meta("linkedin_client_secret") or getattr(config, "LINKEDIN_CLIENT_SECRET", "") or ""
                _cb_li_redirect = _cb_db.get_meta("linkedin_redirect_uri") or getattr(config, "LINKEDIN_REDIRECT_URI", None) or _get_redirect_uri()
                _cb_db.close()
                token_data = exchange_code(
                    client_id=_cb_li_id,
                    client_secret=_cb_li_secret,
                    redirect_uri=_cb_li_redirect,
                    code=params["code"],
                )
                _save_linkedin_token(st.session_state["user_email"], token_data)
                st.session_state["linkedin_connected"] = True
                st.query_params.clear()
                st.rerun()
            except Exception as e:
                st.error(f"LinkedIn sign-in failed: {e}")
                st.query_params.clear()
                st.stop()
        else:
            st.error("LinkedIn OAuth state mismatch. Please try again.")
            st.query_params.clear()
            st.stop()

# Google OAuth callback
elif "code" in params and "user_email" not in st.session_state:
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
linkedin_token = _load_linkedin_token(user_email)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(f"**{user_email}**")
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()

    # ── Gmail Sync ────────────────────────────────────────────────────────
    st.divider()
    st.header("Gmail Sync")

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

    if st.button("Push All to Notion"):
        notion_key = db.get_meta("notion_api_key") or ""
        notion_db = db.get_meta("notion_database_id") or ""
        if not notion_key or not notion_db:
            st.warning("Set your Notion API Key and Database ID first (see Notion Settings below).")
        else:
            all_emails = {c["email"] for c in db.get_all_contacts()}
            if not all_emails:
                st.info("No contacts to push. Run a sync first.")
            else:
                with st.spinner(f"Pushing {len(all_emails)} contacts to Notion..."):
                    try:
                        from main import sync_to_notion
                        sync_to_notion(db, all_emails,
                                       notion_api_key=notion_key,
                                       notion_database_id=notion_db)
                        st.success(f"Pushed {len(all_emails)} contacts to Notion!")
                    except Exception as e:
                        st.error(f"Notion push failed: {e}")

    # ── LinkedIn ──────────────────────────────────────────────────────────
    st.divider()
    st.header("LinkedIn")

    if linkedin_token:
        st.caption("LinkedIn connected")
        if st.button("Sync LinkedIn", type="primary"):
            with st.spinner("Fetching LinkedIn connections..."):
                try:
                    from linkedin_client import fetch_connections
                    from linkedin_sync import LinkedInNotionSync

                    access_token = linkedin_token.get("access_token", "")
                    raw_connections = fetch_connections(access_token)

                    # Store in local DB
                    count = 0
                    for conn in raw_connections:
                        linkedin_url = conn.get("profileUrl", conn.get("publicProfileUrl", ""))
                        if not linkedin_url:
                            continue
                        db.store_linkedin_connection(
                            linkedin_url=linkedin_url,
                            first_name=conn.get("firstName", ""),
                            last_name=conn.get("lastName", ""),
                            email=conn.get("emailAddress", ""),
                            company=conn.get("company", ""),
                            position=conn.get("position", ""),
                            connected_on=conn.get("connectedAt", ""),
                        )
                        count += 1

                    # Sync to Notion if configured
                    li_notion_key = db.get_meta("linkedin_notion_api_key") or ""
                    li_notion_db = db.get_meta("linkedin_notion_database_id") or ""
                    notion_synced = 0
                    if li_notion_key and li_notion_db:
                        li_sync = LinkedInNotionSync(li_notion_key, li_notion_db)
                        li_sync.load_existing_connections()
                        for c in db.get_all_linkedin_connections():
                            li_sync.sync_connection(c)
                            notion_synced += 1

                    msg = f"Done — {count} connections stored"
                    if notion_synced:
                        msg += f", {notion_synced} synced to Notion"
                    st.success(msg)
                    st.rerun()
                except Exception as e:
                    st.error(f"LinkedIn sync failed: {e}")
    else:
        li_client_id = db.get_meta("linkedin_client_id") or getattr(config, "LINKEDIN_CLIENT_ID", None)
        if li_client_id:
            from linkedin_client import get_auth_url
            li_secret = db.get_meta("linkedin_client_secret") or getattr(config, "LINKEDIN_CLIENT_SECRET", "")
            li_redirect = db.get_meta("linkedin_redirect_uri") or getattr(config, "LINKEDIN_REDIRECT_URI", None) or _get_redirect_uri()
            state = f"linkedin_{secrets.token_urlsafe(16)}"
            st.session_state["linkedin_state"] = state
            li_auth_url = get_auth_url(li_client_id, li_redirect, state)
            st.link_button("Sign in with LinkedIn", li_auth_url)
        else:
            st.caption("Configure LinkedIn credentials below to enable")

    li_conn_count = db.get_linkedin_connection_count()
    if li_conn_count:
        st.caption(f"{li_conn_count} connections stored")

    with st.expander("LinkedIn App Settings"):
        saved_li_client_id = db.get_meta("linkedin_client_id") or ""
        saved_li_client_secret = db.get_meta("linkedin_client_secret") or ""
        saved_li_redirect_uri = db.get_meta("linkedin_redirect_uri") or ""

        li_client_id_input = st.text_input(
            "LinkedIn Client ID",
            value=saved_li_client_id,
            help="From LinkedIn Developer Portal",
            key="linkedin_client_id",
        )
        li_client_secret_input = st.text_input(
            "LinkedIn Client Secret",
            value=saved_li_client_secret,
            type="password",
            help="From LinkedIn Developer Portal",
            key="linkedin_client_secret",
        )
        li_redirect_uri_input = st.text_input(
            "Redirect URI",
            value=saved_li_redirect_uri or _get_redirect_uri(),
            help="Must match the redirect URI in your LinkedIn app",
            key="linkedin_redirect_uri",
        )

        if st.button("Save LinkedIn App Settings"):
            db.set_meta("linkedin_client_id", li_client_id_input.strip())
            db.set_meta("linkedin_client_secret", li_client_secret_input.strip())
            db.set_meta("linkedin_redirect_uri", li_redirect_uri_input.strip())
            st.success("Saved!")
            st.rerun()

    # ── Filters ───────────────────────────────────────────────────────────
    st.divider()
    st.header("Filters")
    search_query = st.text_input("Search by email", placeholder="e.g. alice@")
    days_range = st.slider("Days since last contact", 0, 365, (0, 365))

    # ── Notion settings (Gmail) ───────────────────────────────────────────
    st.divider()
    with st.expander("Gmail Notion Settings"):
        saved_key = db.get_meta("notion_api_key") or ""
        saved_db_id = db.get_meta("notion_database_id") or ""

        notion_api_key = st.text_input(
            "Notion API Key",
            value=saved_key,
            type="password",
            help="From notion.so/my-integrations",
            key="gmail_notion_key",
        )
        notion_database_id = st.text_input(
            "Notion Database ID",
            value=saved_db_id,
            help="The ID from your Notion database URL",
            key="gmail_notion_db",
        )

        if st.button("Save Gmail Notion Settings"):
            db.set_meta("notion_api_key", notion_api_key.strip())
            db.set_meta("notion_database_id", notion_database_id.strip())
            st.success("Saved!")

    # ── Notion settings (LinkedIn) ────────────────────────────────────────
    with st.expander("LinkedIn Notion Settings"):
        saved_li_key = db.get_meta("linkedin_notion_api_key") or ""
        saved_li_db_id = db.get_meta("linkedin_notion_database_id") or ""

        li_notion_api_key = st.text_input(
            "Notion API Key",
            value=saved_li_key,
            type="password",
            help="From notion.so/my-integrations",
            key="linkedin_notion_key",
        )
        li_notion_database_id = st.text_input(
            "Notion Database ID",
            value=saved_li_db_id,
            help="The ID from your LinkedIn connections Notion database URL",
            key="linkedin_notion_db",
        )

        if st.button("Save LinkedIn Notion Settings"):
            db.set_meta("linkedin_notion_api_key", li_notion_api_key.strip())
            db.set_meta("linkedin_notion_database_id", li_notion_database_id.strip())
            st.success("Saved!")

# ── Main content area with tabs ───────────────────────────────────────────────

gmail_tab, linkedin_tab = st.tabs(["Gmail Contacts", "LinkedIn Connections"])

# ── Gmail tab ─────────────────────────────────────────────────────────────────

with gmail_tab:
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

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Email", "Name", "Total Emails", "Threads",
                 "First Contact", "Last Contact", "30d Count",
                 "90d Count", "Days Since Last"]
    )

    # Apply filters
    if search_query:
        df = df[df["Email"].str.contains(search_query, case=False, na=False)]

    if not df.empty and "Days Since Last" in df.columns:
        mask = df["Days Since Last"].notna()
        df = df[
            ~mask
            | ((df["Days Since Last"] >= days_range[0]) & (df["Days Since Last"] <= days_range[1]))
        ]

    # Summary metrics
    st.subheader("Email Engagement Dashboard")

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

    # Contact table
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

# ── LinkedIn tab ──────────────────────────────────────────────────────────────

with linkedin_tab:
    li_connections = db.get_all_linkedin_connections()

    li_rows = []
    for c in li_connections:
        li_rows.append({
            "Name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
            "Company": c.get("company", ""),
            "Position": c.get("position", ""),
            "Email": c.get("email", ""),
            "Connected On": (c.get("connected_on") or "")[:10],
            "LinkedIn URL": c.get("linkedin_url", ""),
        })

    li_df = pd.DataFrame(li_rows) if li_rows else pd.DataFrame(
        columns=["Name", "Company", "Position", "Email", "Connected On", "LinkedIn URL"]
    )

    col1, col2 = st.columns(2)
    col1.metric("Total Connections", len(li_df))
    if not li_df.empty:
        companies = li_df["Company"].value_counts()
        if not companies.empty and companies.index[0]:
            col2.metric("Top Company", companies.index[0])
        else:
            col2.metric("Top Company", "—")
    else:
        col2.metric("Top Company", "—")

    st.subheader(f"Connections ({len(li_df)})")
    st.dataframe(
        li_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "LinkedIn URL": st.column_config.LinkColumn("Profile"),
        },
    )

db.close()
