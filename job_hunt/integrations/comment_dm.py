"""Instagram comment-to-DM automation.

Someone comments on a Reel (``LINK`` or, by default, anything) -> Instagram sends
a ``comments`` webhook -> we send that person a private reply (a DM) with the
application link and, optionally, a short public reply ("Sent you a DM 📩").

Requires an Instagram professional account connected through "Instagram API
with Instagram Login" with these permissions:
  instagram_business_basic, instagram_business_manage_comments,
  instagram_business_manage_messages
and the app's webhook subscribed to the ``comments`` field.

Instagram allows one private reply per comment, within 7 days of the comment.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import random
import re

import requests

from ..config import comment_keyword, comment_to_dm_enabled, env_flag, load_environment
from . import link_store

load_environment()
logger = logging.getLogger(__name__)

GRAPH_API_VERSION = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v25.0")
GRAPH = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

DEFAULT_DM = (
    "Hi {username} 👋\n\n"
    "Here's the apply link for {role_at_company}:\n{link}\n\n"
    "✅ Please verify the role on the company's official careers page.\n"
    "🔔 Follow us for daily tech jobs & internships. All the best!"
)
# Text shown above the tappable "Apply Now" button (Instagram limit: 640 chars).
DEFAULT_BUTTON_DM = (
    "Hi {username} 👋\n\n"
    "Here's the apply link for {role_at_company} 👇\n\n"
    "✅ Verify the role on the company's official careers page.\n"
    "🔔 Follow us for daily tech jobs & internships!"
)
DEFAULT_BUTTON_TITLE = "Apply Now"
DEFAULT_PUBLIC_REPLIES = [
    "Sent you the link in DMs 📩",
    "Check your DMs 📩 All the best!",
    "Link sent to your inbox 🚀",
    "Done! Check your DMs ✅",
]


# --- request verification ---------------------------------------------------

def verify_subscription(mode, token, challenge):
    """GET handshake from Meta when you add the callback URL."""
    expected = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "")
    if mode == "subscribe" and expected and hmac.compare_digest(token or "", expected):
        return challenge
    return None


def _webhook_secrets():
    """Instagram-login apps sign webhooks with the *Instagram* app secret;
    Facebook-login apps use the main app secret. Accept either."""
    names = ("INSTAGRAM_APP_SECRET", "META_APP_SECRET")
    return [(n, os.getenv(n, "").strip()) for n in names if os.getenv(n, "").strip()]


def signature_is_valid(body: bytes, header: str) -> bool:
    secrets = _webhook_secrets()
    if not secrets:
        logger.error("Set INSTAGRAM_APP_SECRET (or META_APP_SECRET); rejecting Instagram webhook.")
        return False
    header = (header or "").strip().lower()
    if not header.startswith("sha256="):
        return False
    for name, secret in secrets:
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, header):
            return True
    logger.warning("Webhook signature matched none of: %s", ", ".join(n for n, _ in secrets))
    return False


# --- Graph API ---------------------------------------------------------------

def _token():
    token = os.getenv("INSTA_TOKEN")
    if not token:
        raise RuntimeError("INSTA_TOKEN is not set.")
    return token


def _post(path, *, json_body=None, data=None):
    response = requests.post(
        f"{GRAPH}/{path.lstrip('/')}",
        params={"access_token": _token()},
        json=json_body, data=data, timeout=20,
    )
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = response.text[:200]
        raise RuntimeError(f"Instagram API {path} failed ({response.status_code}): {message}")
    return response.json()


def _caption_link(media_id):
    """Fallback when the link store has no record: read the post caption."""
    try:
        response = requests.get(
            f"{GRAPH}/{media_id}",
            params={"fields": "caption", "access_token": _token()}, timeout=15,
        )
        response.raise_for_status()
        match = URL_RE.search(response.json().get("caption") or "")
        return match.group(0).rstrip(".,;:!") if match else None
    except Exception:
        logger.exception("Could not read caption for media %s", media_id)
        return None


def send_private_reply(comment_id, text):
    result = _post(f"{os.getenv('INSTAGRAM_USER_ID') or 'me'}/messages",
                   json_body={"recipient": {"comment_id": str(comment_id)}, "message": {"text": text}})
    if not result.get("message_id"):
        raise RuntimeError("Instagram did not confirm the private reply.")
    return result["message_id"]


def send_private_reply_button(comment_id, text, url, title=DEFAULT_BUTTON_TITLE):
    """Private reply with a tappable web_url button.

    Plain-text links in a DM from an account the person doesn't follow land in
    Message Requests, where Instagram shows them as unclickable text. A button
    template renders a real button that opens the link.
    """
    payload = {
        "template_type": "button",
        "text": text[:640],
        "buttons": [{"type": "web_url", "url": url, "title": (title or DEFAULT_BUTTON_TITLE)[:20]}],
    }
    result = _post(f"{os.getenv('INSTAGRAM_USER_ID') or 'me'}/messages",
                   json_body={"recipient": {"comment_id": str(comment_id)},
                              "message": {"attachment": {"type": "template", "payload": payload}}})
    if not result.get("message_id"):
        raise RuntimeError("Instagram did not confirm the button reply.")
    return result["message_id"]


def deliver_link(comment_id, username, record, link):
    """Send the apply link as a button; fall back to plain text if refused.

    Instagram allows only ONE private reply per comment, so the fallback is only
    attempted when the button request itself was rejected (nothing delivered).
    """
    if env_flag("COMMENT_DM_BUTTON", True):
        try:
            return send_private_reply_button(comment_id, _render_dm(username, record, link, button=True), link,
                                             os.getenv("COMMENT_DM_BUTTON_TITLE") or DEFAULT_BUTTON_TITLE)
        except Exception as exc:
            logger.warning("Button DM refused for comment %s (%s); sending plain text instead.",
                           comment_id, str(exc)[:200])
    return send_private_reply(comment_id, _render_dm(username, record, link))


def send_public_reply(comment_id, text):
    return _post(f"{comment_id}/replies", data={"message": text})


# --- comment handling ----------------------------------------------------------

def _keywords():
    words = {w.strip().lower() for w in os.getenv("COMMENT_DM_KEYWORDS", "").split(",") if w.strip()}
    keyword = comment_keyword()
    if keyword:
        words.add(keyword.lower())
    return words


def comment_matches(text):
    """``COMMENT_DM_TRIGGER=any`` (default): every comment gets the link.
    ``COMMENT_DM_TRIGGER=keyword``: only comments containing COMMENT_KEYWORD or
    one of COMMENT_DM_KEYWORDS (comma separated)."""
    if os.getenv("COMMENT_DM_TRIGGER", "any").strip().lower() != "keyword":
        return bool((text or "").strip())
    lowered = (text or "").lower()
    return any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in _keywords())


def _is_own_comment(value, account_id):
    sender = value.get("from") or {}
    own_ids = {str(account_id or ""), os.getenv("INSTAGRAM_USER_ID", "")} - {""}
    own_name = os.getenv("INSTAGRAM_USERNAME", "").lstrip("@").lower()
    return str(sender.get("id", "")) in own_ids or (own_name and sender.get("username", "").lower() == own_name)


def _render_dm(username, record, link, button=False):
    role, company = (record or {}).get("role"), (record or {}).get("company")
    if role and company:
        role_at_company = f"{role} at {company}"
    else:
        role_at_company = role or company or "this role"
    if button:
        template = os.getenv("COMMENT_DM_BUTTON_MESSAGE") or DEFAULT_BUTTON_DM
        limit = 640
    else:
        template = os.getenv("COMMENT_DM_MESSAGE") or DEFAULT_DM
        limit = 1000
    template = template.replace("\\n", "\n")
    return template.format(username=f"@{username}" if username else "there",
                           role_at_company=role_at_company, role=role or "", company=company or "",
                           link=link)[:limit]


def process_comment(value, account_id=None):
    """Handle one ``comments`` change. Returns a short status string (for logs/tests)."""
    if not comment_to_dm_enabled():
        return "disabled"
    comment_id = value.get("id")
    media_id = (value.get("media") or {}).get("id")
    sender = value.get("from") or {}
    if not comment_id or not media_id:
        return "incomplete"
    if _is_own_comment(value, account_id):
        return "own-comment"  # never answer our own public replies (loop guard)
    if not comment_matches(value.get("text")):
        return "no-match"

    record = link_store.get_media_record(media_id)
    link = (record or {}).get("short_link") or _caption_link(media_id)
    if not link:
        logger.warning("No application link known for media %s", media_id)
        return "no-link"

    if not link_store.claim(f"c:{comment_id}"):
        return "duplicate"
    user_key = f"u:{media_id}:{sender.get('id')}" if sender.get("id") else None
    if user_key and env_flag("COMMENT_DM_ONCE_PER_USER", True) and not link_store.claim(user_key):
        return "already-sent-to-user"

    try:
        deliver_link(comment_id, sender.get("username"), record, link)
    except Exception:
        link_store.release(f"c:{comment_id}")
        if user_key:
            link_store.release(user_key)
        logger.exception("Private reply failed for comment %s", comment_id)
        return "dm-failed"

    if env_flag("COMMENT_PUBLIC_REPLY", True):
        try:
            replies = [r.strip() for r in os.getenv("COMMENT_PUBLIC_REPLIES", "").split("|") if r.strip()]
            send_public_reply(comment_id, random.choice(replies or DEFAULT_PUBLIC_REPLIES))
        except Exception:
            logger.exception("Public reply failed for comment %s (DM was sent)", comment_id)
    logger.info("Comment-to-DM sent for comment %s on media %s", comment_id, media_id)
    return "sent"


def comment_events(payload):
    """Yield (value, account_id) for each comment change in a webhook payload."""
    if payload.get("object") != "instagram":
        return
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                yield change.get("value") or {}, entry.get("id")
