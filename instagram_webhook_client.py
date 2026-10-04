import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()


def register_published_media(media_id, short_link):
    base_url = os.getenv("INSTAGRAM_WEBHOOK_URL", "").rstrip("/")
    admin_token = os.getenv("WEBHOOK_ADMIN_TOKEN")
    if not base_url or not admin_token:
        raise RuntimeError(
            "Set INSTAGRAM_WEBHOOK_URL and WEBHOOK_ADMIN_TOKEN in .env."
        )

    request = Request(
        f"{base_url}/admin/media",
        data=json.dumps({
            "media_id": str(media_id),
            "short_link": short_link,
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status != 201:
                raise RuntimeError(
                    f"Webhook service rejected the Reel mapping "
                    f"(HTTP {response.status})."
                )
    except HTTPError as error:
        raise RuntimeError(
            f"Webhook service rejected the Reel mapping (HTTP {error.code})."
        ) from error
    except URLError as error:
        raise RuntimeError(
            f"Could not reach Instagram webhook service: {error.reason}"
        ) from error
