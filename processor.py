from __future__ import annotations

import re
import logging
from email.utils import parseaddr, getaddresses

import config

log = logging.getLogger(__name__)


def normalize_email(raw: str) -> str | None:
    """Extract and normalize an email address.
    Strips display names, lowercases, removes + aliases."""
    _, addr = parseaddr(raw)
    if not addr or "@" not in addr:
        return None
    addr = addr.lower().strip()
    # Remove + aliases (user+tag@gmail.com -> user@gmail.com)
    local, domain = addr.split("@", 1)
    if "+" in local:
        local = local.split("+")[0]
    return f"{local}@{domain}"


def is_my_email(email: str) -> bool:
    """Check if this email belongs to the user."""
    normalized = normalize_email(email)
    if not normalized:
        return False
    return normalized in config.MY_EMAIL_ADDRESSES


# Automated / noreply local parts (before the @)
_NOREPLY_LOCALS = {
    "noreply", "no-reply", "no_reply",
    "donotreply", "do-not-reply", "do_not_reply",
    "mailer-daemon", "postmaster",
    "unsubscribe", "bounce", "bounces",
    "notifications", "notification",
    "alerts", "alert",
    "news", "newsletter",
    "marketing", "promo", "promotions",
    "support", "help", "info", "feedback",
    "billing", "invoice", "invoices", "receipts",
    "shipment", "shipping", "order", "orders",
    "auto", "automated", "autoresponder",
    "system", "admin", "root",
}

# Domains that are almost always automated / transactional
_AUTOMATED_DOMAINS = {
    # Email / marketing platforms
    "mailchimp.com", "mandrillapp.com", "sendgrid.net", "sendgrid.com",
    "mailgun.org", "mailgun.com", "amazonses.com", "postmarkapp.com",
    "constantcontact.com", "campaign-archive.com", "createsend.com",
    "hubspot.com", "hubspotmail.com", "hs-mail.com",
    "klaviyo.com", "brevo.com", "sendinblue.com",
    # Transactional / notifications
    "facebookmail.com", "linkedin.com", "twitter.com", "x.com",
    "pinterest.com", "instagram.com", "tiktok.com",
    "accounts.google.com", "noreply.github.com",
    "shopify.com", "squarespace.com", "wix.com",
    "stripe.com", "paypal.com", "venmo.com",
    "uber.com", "lyft.com", "doordash.com", "grubhub.com",
    "netflix.com", "spotify.com", "apple.com",
    "zoom.us", "calendly.com",
    "slack.com", "notion.so", "atlassian.net",
    "jira.com", "trello.com", "asana.com",
    "intercom.io", "zendesk.com", "freshdesk.com",
}


def is_automated_email(email: str) -> bool:
    """Return True if the email looks like an automated / non-human address."""
    if not email or "@" not in email:
        return False

    local, domain = email.split("@", 1)

    # Check local part
    if local in _NOREPLY_LOCALS:
        return True

    # Check domain
    # Match "sub.example.com" against "example.com"
    for automated_domain in _AUTOMATED_DOMAINS:
        if domain == automated_domain or domain.endswith("." + automated_domain):
            return True

    return False


def extract_recipients(message: dict) -> list[dict]:
    """Parse To/Cc/Bcc headers into a list of {email, field} dicts.
    Filters out the user's own addresses."""
    recipients = []
    seen = set()

    for field in ("to", "cc", "bcc"):
        raw = message.get(field, "")
        if not raw:
            continue
        # getaddresses handles comma-separated lists with display names
        for _name, addr in getaddresses([raw]):
            normalized = normalize_email(addr)
            if not normalized:
                continue
            if is_my_email(normalized):
                continue
            if is_automated_email(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            recipients.append({"email": normalized, "field": field})

    return recipients


def process_message(message: dict) -> dict | None:
    """Process a raw Gmail message dict into a storable format.
    Returns None if the message should be skipped."""
    recipients = extract_recipients(message)
    if not recipients:
        log.debug("Skipping message %s — no external recipients", message["message_id"])
        return None

    return {
        "message_id": message["message_id"],
        "thread_id": message["thread_id"],
        "sent_at": message["sent_at"],
        "sender": normalize_email(message["from"]) or message["from"],
        "recipients": recipients,
    }
