# Email Relationship Intelligence Tool

A personal CRM that tracks your email engagement by syncing Gmail sent-mail data into SQLite and Notion.

## What It Does

- Connects to your Gmail via OAuth2
- Reads your **sent mail** and tracks who you email, how often, and when
- Computes per-contact metrics: total emails, first/last contact, 30/90-day counts, unique threads
- Stores everything in a local SQLite database for fast querying
- Syncs contact data to a Notion database for a visual dashboard
- Runs incrementally — only processes new emails on subsequent runs

## Project Structure

```
main.py           — Orchestrator: runs the full sync pipeline
gmail_client.py   — Gmail API auth + message fetching
processor.py      — Email parsing, normalization, recipient extraction
database.py       — SQLite persistence layer
notion_sync.py    — Notion API upsert logic
config.py         — Environment variable loading
```

## Setup

### 1. Python Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable the **Gmail API**: APIs & Services → Library → search "Gmail API" → Enable
4. Create OAuth credentials:
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: **Desktop app**
   - Download the JSON file
5. Save it as `credentials.json` in the project root
6. Required scope: `https://www.googleapis.com/auth/gmail.readonly`

On first run, a browser window opens for you to authorize. The token is saved to `token.json` for subsequent runs.

### 3. Notion Integration

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Create a new integration:
   - Give it a name (e.g. "Email CRM")
   - Select your workspace
   - Capabilities: Read + Update + Insert content
3. Copy the **Internal Integration Token** (starts with `secret_`)
4. Create a Notion database with these properties:

| Property               | Type      |
|------------------------|-----------|
| Name                   | Title     |
| Email                  | Rich Text |
| Total Emails           | Number    |
| First Contact          | Date      |
| Last Contact           | Date      |
| 30 Day Count           | Number    |
| 90 Day Count           | Number    |
| Unique Threads         | Number    |
| Days Since Last Contact| Number    |

5. **Connect** the integration to your database:
   - Open the database page in Notion
   - Click `...` → Connections → Add your integration
6. Copy the **Database ID** from the page URL:
   - URL looks like: `https://notion.so/workspace/DATABASE_ID?v=...`
   - The DATABASE_ID is the 32-character hex string before the `?`

### 4. Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your values:

```
GOOGLE_CREDENTIALS_FILE=credentials.json
NOTION_API_KEY=secret_your_token_here
NOTION_DATABASE_ID=your_database_id_here
MY_EMAIL_ADDRESSES=you@gmail.com
```

`MY_EMAIL_ADDRESSES` is optional — if omitted, it auto-detects from your Gmail profile.

## Running

```bash
# First run (backfills entire sent history)
python main.py

# Subsequent runs (incremental — only new emails)
python main.py
```

### Scheduling with Cron

Run daily at 8am:

```bash
crontab -e
```

Add:

```
0 8 * * * cd /path/to/project && /path/to/venv/bin/python main.py >> /path/to/project/cron.log 2>&1
```

## How Incremental Sync Works

1. On first run, fetches all sent-mail message IDs from Gmail
2. Fetches metadata for each message and stores in SQLite
3. Saves the timestamp of the most recent email processed
4. On next run, only fetches messages sent after that timestamp
5. Each message ID is checked against the database — never double-counted
6. Only contacts affected by new emails are recalculated and synced to Notion

## Data Storage

All data lives in `email_crm.db` (SQLite). Tables:

- **emails_processed** — every sent email (message ID, thread ID, timestamp)
- **email_recipients** — who received each email (to/cc/bcc)
- **contacts** — computed metrics per email address
- **metadata** — sync state (last timestamp)

## Troubleshooting

- **Token expired**: Delete `token.json` and re-run to re-authenticate
- **Rate limited**: The tool automatically backs off and retries
- **Notion 400 errors**: Verify your database properties match the expected names and types exactly
- **Large inbox**: First run may take a while for 100k+ emails — progress is logged every 100 messages
