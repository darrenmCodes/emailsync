# Notion Setup Guide

## Step 1: Create a Notion Integration

1. Go to https://www.notion.so/my-integrations
2. Click **"New integration"**
3. Give it a name (e.g. "Email Sync")
4. Select the workspace you want to use
5. Click **"Submit"**
6. Copy the **Internal Integration Secret** (starts with `ntn_`) — this is your **Notion API Key**

## Step 2: Create the Notion Database

Create a new **full-page database** in Notion with exactly these properties:

| Property Name           | Type   |
|-------------------------|--------|
| Name                    | Title  |
| Email                   | Email  |
| Total Emails            | Number |
| First Contact           | Date   |
| Last Contact            | Date   |
| 30 Day Count            | Number |
| 90 Day Count            | Number |
| Unique Threads          | Number |
| Days Since Last Contact | Number |

Property names must match exactly (they are case-sensitive).

**To add properties:** Open the database, click **"+"** at the top right of the table header to add each column, then set the name and type as listed above.

## Step 3: Connect the Integration to the Database

1. Open the database page in Notion
2. Click the **"..."** menu in the top-right corner
3. Go to **"Connections"**
4. Find your integration (e.g. "Email Sync") and click **"Connect"**
5. Confirm the connection

Without this step, the integration cannot read or write to the database.

## Step 4: Get the Database ID

1. Open the database in Notion in your browser
2. Look at the URL — it will look like:
   ```
   https://www.notion.so/yourworkspace/abc123def456?v=...
   ```
3. The **Database ID** is the long alphanumeric string before the `?v=` part
   - In the example above: `abc123def456`
4. Copy this value

## Step 5: Add to the App

1. Open the app in your browser
2. Sign in with Google
3. In the left sidebar, expand **"Notion Settings"**
4. Paste your **Notion API Key** (from Step 1)
5. Paste your **Notion Database ID** (from Step 4)
6. Click **"Save Notion Settings"**

## Step 6: Sync

Click **"Sync Now"** in the sidebar. The app will:

1. Fetch your sent emails from Gmail
2. Compute engagement metrics per contact
3. Create or update rows in your Notion database

Each contact gets a row with their email, total emails sent, first/last contact dates, 30-day and 90-day email counts, unique threads, and days since last contact.

## Troubleshooting

- **"NOTION_API_KEY not set"** — Make sure you pasted the API key in Notion Settings and clicked Save
- **"Failed to query Notion database"** — Make sure the integration is connected to the database (Step 3)
- **Properties not syncing** — Double-check that all property names and types match the table in Step 2 exactly
