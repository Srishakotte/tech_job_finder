import hashlib
import hmac
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from instagram_link_store import (
    claim_comment,
    get_media_link,
    mark_comment_failed,
    mark_comment_sent,
)

load_dotenv()

logger = logging.getLogger(__name__)
GRAPH_API_VERSION = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v25.0")
GRAPH_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
MAX_WEBHOOK_BODY_BYTES = 1024 * 1024
DM_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="instagram-dm")


def _response(start_response, status, body, content_type="text/plain; charset=utf-8"):
    payload = body.encode("utf-8") if isinstance(body, str) else body
    start_response(
        status,
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(payload))),
        ],
    )
    return [payload]


def _is_valid_signature(body, supplied_signature, app_secret):
    supplied_signature = supplied_signature.strip().lower()
    app_secret = app_secret.strip()
    if not supplied_signature or not supplied_signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, supplied_signature)


def _send_private_reply(comment_id, short_link):
    access_token = os.getenv("INSTA_TOKEN")
    instagram_user_id = os.getenv("INSTAGRAM_USER_ID")
    if not access_token or not instagram_user_id:
        raise RuntimeError("Instagram messaging credentials are not configured.")

    message = (
        f"Here’s the application link: {short_link}\n\n"
        "This link may show ads, and we may earn from visits. "
        "Please verify the role on the employer’s official careers page."
    )
    payload = {
        "recipient": {"comment_id": str(comment_id)},
        "message": {"text": message},
    }
    request = Request(
        f"{GRAPH_API_BASE}/{instagram_user_id}/messages?access_token={access_token}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(
            f"Instagram private reply failed with HTTP {error.code}."
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Instagram messaging API: {error.reason}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Instagram returned an invalid private-reply response.") from error

    if not result.get("message_id"):
        raise RuntimeError("Instagram did not confirm the private reply.")


def _process_comment(comment):
    comment_id = comment.get("id")
    media = comment.get("media") or {}
    media_id = media.get("id")
    text = comment.get("text") or ""

    if not comment_id or not media_id or not re.search(
        r"\b(?:apply|link)\b",
        text,
        re.IGNORECASE,
    ):
        return

    short_link = get_media_link(media_id)
    if not short_link:
        logger.warning("No saved application link found for Instagram media %s.", media_id)
        return
    if not claim_comment(comment_id):
        return

    try:
        _send_private_reply(comment_id, short_link)
        mark_comment_sent(comment_id)
        logger.info("Sent application link by private reply for comment %s.", comment_id)
    except Exception:
        mark_comment_failed(comment_id)
        logger.exception("Could not send application link for comment %s.", comment_id)


def _process_payload(payload):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            value = change.get("value") or {}
            DM_EXECUTOR.submit(_process_comment, value)


def application(environ, start_response):
    path = environ.get("PATH_INFO")
    if path == "/health" and environ.get("REQUEST_METHOD", "GET").upper() == "GET":
        return _response(start_response, "200 OK", "ok")
    if path == "/admin/media":
        return _register_media_link(environ, start_response)
    if path != "/webhook":
        return _response(start_response, "404 Not Found", "Not found")

    method = environ.get("REQUEST_METHOD", "GET").upper()
    if method == "GET":
        verify_token = os.getenv("META_WEBHOOK_VERIFY_TOKEN")
        if not verify_token:
            return _response(
                start_response,
                "503 Service Unavailable",
                "Webhook verification is not configured.",
            )

        query = parse_qs(environ.get("QUERY_STRING", ""))
        mode = query.get("hub.mode", [""])[0]
        token = query.get("hub.verify_token", [""])[0]
        challenge = query.get("hub.challenge", [""])[0]
        if mode == "subscribe" and hmac.compare_digest(token, verify_token):
            return _response(start_response, "200 OK", challenge)
        return _response(start_response, "403 Forbidden", "Verification failed")

    if method != "POST":
        return _response(start_response, "405 Method Not Allowed", "Method not allowed")

    try:
        content_length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        return _response(start_response, "400 Bad Request", "Invalid content length")
    if content_length <= 0 or content_length > MAX_WEBHOOK_BODY_BYTES:
        return _response(start_response, "413 Payload Too Large", "Invalid webhook body size")

    body = environ["wsgi.input"].read(content_length)
    app_secret = os.getenv("META_APP_SECRET")
    if not app_secret:
        return _response(
            start_response,
            "503 Service Unavailable",
            "Webhook signature verification is not configured.",
        )

    signature = environ.get("HTTP_X_HUB_SIGNATURE_256", "")
    if not _is_valid_signature(body, signature, app_secret):
        logger.warning(
            "Rejected Instagram webhook signature "
            "(signature_header_present=%s, sha256_prefix=%s, body_bytes=%s).",
            bool(signature),
            signature.startswith("sha256="),
            len(body),
        )
        return _response(start_response, "403 Forbidden", "Invalid webhook signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _response(start_response, "400 Bad Request", "Invalid JSON payload")
    if payload.get("object") != "instagram":
        return _response(start_response, "400 Bad Request", "Unexpected webhook object")

    try:
        _process_payload(payload)
    except Exception:
        logger.exception("Could not queue Instagram webhook events.")
        return _response(start_response, "500 Internal Server Error", "Webhook processing failed")

    entries = payload.get("entry", [])
    comment_events = sum(
        1
        for entry in entries
        for change in entry.get("changes", [])
        if change.get("field") == "comments"
    )
    logger.info(
        "Accepted Instagram webhook payload (entries=%d, comment_events=%d).",
        len(entries),
        comment_events,
    )
    return _response(start_response, "200 OK", "EVENT_RECEIVED")


def _register_media_link(environ, start_response):
    if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
        return _response(start_response, "405 Method Not Allowed", "Method not allowed")

    admin_token = os.getenv("WEBHOOK_ADMIN_TOKEN")
    authorization = environ.get("HTTP_AUTHORIZATION", "")
    supplied_token = authorization.removeprefix("Bearer ").strip()
    if not admin_token or not hmac.compare_digest(supplied_token, admin_token):
        return _response(start_response, "401 Unauthorized", "Unauthorized")

    try:
        content_length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        return _response(start_response, "400 Bad Request", "Invalid content length")
    if content_length <= 0 or content_length > 16 * 1024:
        return _response(start_response, "413 Payload Too Large", "Invalid request body size")

    try:
        payload = json.loads(environ["wsgi.input"].read(content_length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _response(start_response, "400 Bad Request", "Invalid JSON payload")

    media_id = payload.get("media_id")
    short_link = payload.get("short_link")
    if not isinstance(media_id, (str, int)) or not isinstance(short_link, str):
        return _response(start_response, "400 Bad Request", "media_id and short_link are required")
    if not short_link.startswith(("https://", "http://")):
        return _response(start_response, "400 Bad Request", "short_link must be an HTTP URL")

    try:
        from instagram_link_store import store_media_link

        store_media_link(media_id, short_link)
    except Exception:
        logger.exception("Could not save Instagram media link mapping.")
        return _response(
            start_response,
            "500 Internal Server Error",
            "Could not save media link mapping",
        )

    return _response(start_response, "201 Created", "saved")


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    port = int(os.getenv("PORT", "8080"))
    logger.info("Starting local Instagram webhook server on port %s.", port)
    make_server("127.0.0.1", port, application).serve_forever()
