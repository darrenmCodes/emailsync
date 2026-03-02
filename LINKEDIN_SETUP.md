# LinkedIn Setup Guide

## Step 1: Create a LinkedIn App

1. Go to https://www.linkedin.com/developers/apps
2. Click **"Create app"**
3. Fill in:
   - **App name**: e.g. "Email Sync"
   - **LinkedIn Page**: Select your company page (or create one — any page works)
   - **App logo**: Upload any image
   - **Legal agreement**: Check the box
4. Click **"Create app"**

## Step 2: Request the Data Portability API

1. On your app page, go to the **"Products"** tab
2. Find **"Member Data Portability"** and click **"Request access"**
3. Select the **"Self Serve"** variant (no LinkedIn approval needed)
4. Accept the terms

This gives you the `r_dma_portability_self_serve` scope, which lets users pull their own connection data via the EU DMA-mandated API.

## Step 3: Configure OAuth Redirect

1. Go to the **"Auth"** tab on your app page
2. Under **"OAuth 2.0 settings"**, find **"Authorized redirect URLs for your app"**
3. Click **"Add redirect URL"**
4. Enter your app URL exactly, e.g.:
   - Local: `http://localhost:8501`
   - Production: `https://yourdomain.com` (whatever your Streamlit app URL is)
5. Click **"Update"**

The redirect URL must match exactly what you enter in the app settings.

## Step 4: Get Your Credentials

On the **"Auth"** tab, you'll see:

- **Client ID** — a string like `86abc1def2gh3i`
- **Client Secret** — click the eye icon to reveal, looks like `AbCdEf123456`

Copy both values.

## Step 5: Add to the App

1. Open the app in your browser and sign in with Google
2. In the left sidebar, expand **"LinkedIn App Settings"**
3. Paste your **Client ID**
4. Paste your **Client Secret**
5. Set the **Redirect URI** to match exactly what you entered in Step 3
6. Click **"Save LinkedIn App Settings"**

## Step 6: Connect Your LinkedIn Account

1. Click **"Sign in with LinkedIn"** in the sidebar
2. LinkedIn will ask you to authorize the app to access your connections
3. Click **"Allow"**
4. You'll be redirected back to the app

## Step 7: Sync Connections

1. Click **"Sync LinkedIn"** in the sidebar
2. Your connections will be fetched and stored locally
3. To also sync to Notion, configure the **"LinkedIn Notion Settings"** with a separate Notion database (see below)

## Optional: LinkedIn Notion Database

If you want connections synced to Notion, create a new database with these properties:

| Property Name  | Type      |
|----------------|-----------|
| Name           | Title     |
| First Name     | Rich Text |
| Last Name      | Rich Text |
| Company        | Rich Text |
| Position       | Rich Text |
| LinkedIn URL   | URL       |
| Email          | Email     |
| Connected On   | Date      |

Then connect your Notion integration to this database (same steps as the Gmail Notion setup) and enter the API key and Database ID under **"LinkedIn Notion Settings"** in the sidebar.
