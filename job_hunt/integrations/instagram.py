import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import load_environment

load_environment()

GRAPH_API_VERSION = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v25.0")
GRAPH_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
CLOUDINARY_API_BASE = "https://api.cloudinary.com/v1_1"
VIDEO_STATUS_TIMEOUT = 180
VIDEO_STATUS_INTERVAL = 5


def _required_config(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} in .env before publishing.")
    return value


def _read_json_response(request, timeout=60):
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as error:
        try:
            payload = error.read()
            details = json.loads(payload.decode("utf-8"))
            message = details.get("error", {}).get("message")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            message = None
        if message:
            raise RuntimeError(f"Remote API request failed: {message}") from error
        raise RuntimeError(
            f"Remote API request failed with HTTP {error.code}."
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not reach remote API: {error.reason}") from error

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Remote API returned an invalid JSON response.") from error


def _graph_post(path, fields):
    request = Request(
        f"{GRAPH_API_BASE}/{path.lstrip('/')}",
        data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return _read_json_response(request)


def _graph_get(path, fields):
    query = urlencode(fields)
    request = Request(f"{GRAPH_API_BASE}/{path.lstrip('/')}?{query}")
    return _read_json_response(request)


def _cloudinary_signature(parameters, api_secret):
    canonical = "&".join(
        f"{key}={value}"
        for key, value in sorted(parameters.items())
        if value is not None
    )
    return hashlib.sha1(f"{canonical}{api_secret}".encode("utf-8")).hexdigest()


def upload_reel(video_path):
    cloud_name = _required_config("CLOUDINARY_CLOUD_NAME")
    api_key = _required_config("CLOUDINARY_API_KEY")
    api_secret = _required_config("CLOUDINARY_API_SECRET")
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Reel file does not exist: {path}")

    timestamp = str(int(time.time()))
    public_id = f"jobhunter_{path.stem}_{uuid.uuid4().hex[:10]}"
    parameters = {
        "folder": "jobhunter-temporary",
        "public_id": public_id,
        "timestamp": timestamp,
    }
    form_fields = {
        **parameters,
        "api_key": api_key,
        "signature": _cloudinary_signature(parameters, api_secret),
    }
    boundary = f"----JobHunter{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in form_fields.items():
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii")
        )
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("ascii"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{path.name}"\r\n'
        ).encode("utf-8")
    )
    body.extend(b"Content-Type: video/mp4\r\n\r\n")
    body.extend(path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))

    request = Request(
        f"{CLOUDINARY_API_BASE}/{cloud_name}/video/upload",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    result = _read_json_response(request, timeout=120)
    secure_url = result.get("secure_url")
    returned_public_id = result.get("public_id")
    if not secure_url or not returned_public_id:
        raise RuntimeError("Cloudinary upload response is missing the video URL.")
    return {"url": secure_url, "public_id": returned_public_id}


def delete_hosted_reel(public_id):
    cloud_name = _required_config("CLOUDINARY_CLOUD_NAME")
    api_key = _required_config("CLOUDINARY_API_KEY")
    api_secret = _required_config("CLOUDINARY_API_SECRET")
    timestamp = str(int(time.time()))
    parameters = {
        "invalidate": "true",
        "public_id": public_id,
        "timestamp": timestamp,
    }
    fields = {
        **parameters,
        "api_key": api_key,
        "signature": _cloudinary_signature(parameters, api_secret),
    }
    request = Request(
        f"{CLOUDINARY_API_BASE}/{cloud_name}/video/destroy",
        data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    result = _read_json_response(request)
    if result.get("result") not in {"ok", "not found"}:
        raise RuntimeError("Cloudinary did not confirm deletion of the temporary Reel.")


def _wait_for_container(container_id, access_token):
    deadline = time.monotonic() + VIDEO_STATUS_TIMEOUT
    while time.monotonic() < deadline:
        result = _graph_get(
            container_id,
            {"fields": "status_code,status", "access_token": access_token},
        )
        status = result.get("status_code")
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            detail = result.get("status") or status
            raise RuntimeError(f"Instagram could not process the Reel: {detail}")
        time.sleep(VIDEO_STATUS_INTERVAL)

    raise TimeoutError(
        f"Instagram did not finish processing the Reel within "
        f"{VIDEO_STATUS_TIMEOUT} seconds."
    )


def publish_reel(video_path, caption):
    access_token = _required_config("INSTA_TOKEN")
    instagram_user_id = _required_config("INSTAGRAM_USER_ID")
    if len(caption) > 2200:
        raise ValueError(
            f"Instagram captions must be at most 2,200 characters; "
            f"this caption has {len(caption)}."
        )

    hosted_reel = upload_reel(video_path)
    media_id = None
    cleanup_error = None
    try:
        container = _graph_post(
            f"{instagram_user_id}/media",
            {
                "media_type": "REELS",
                "video_url": hosted_reel["url"],
                "caption": caption,
                "share_to_feed": "true",
                "access_token": access_token,
            },
        )
        container_id = container.get("id")
        if not container_id:
            raise RuntimeError("Instagram did not return a Reel container ID.")

        _wait_for_container(container_id, access_token)
        published = _graph_post(
            f"{instagram_user_id}/media_publish",
            {
                "creation_id": container_id,
                "access_token": access_token,
            },
        )
        media_id = published.get("id")
        if not media_id:
            raise RuntimeError("Instagram did not return a published media ID.")
    finally:
        try:
            delete_hosted_reel(hosted_reel["public_id"])
        except Exception as error:
            cleanup_error = str(error)

    return {
        "media_id": media_id,
        "cleanup_error": cleanup_error,
    }
