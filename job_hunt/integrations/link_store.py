"""Instagram media -> application link mapping, plus comment de-duplication.

Backends:
* MongoDB (set ``MONGODB_URI``) - recommended on Render, whose disk is wiped on
  every deploy/restart. A free MongoDB Atlas cluster is enough.
* JSON file in ``DATA_DIR`` - fine for local runs.

If the mapping is ever missing, the comment-to-DM webhook falls back to reading
the link from the post caption, so DMs keep working even without a database.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from ..config import DATA_DIR, load_environment

load_environment()
logger = logging.getLogger(__name__)
_lock = threading.Lock()
_mongo_db = None


def _mongo():
    global _mongo_db
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        return None
    if _mongo_db is None:
        from pymongo import MongoClient

        client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        name = os.getenv("MONGODB_DATABASE") or os.getenv("MONGODB_DB") or "job_hunt"
        _mongo_db = client[name]
        _mongo_db.comments.create_index("created_at", expireAfterSeconds=30 * 24 * 3600)
    return _mongo_db


def _file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "instagram_links.json"


def _load():
    path = _file()
    if not path.is_file():
        return {"media": {}, "comments": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Link store is unreadable; starting fresh")
        return {"media": {}, "comments": {}}


def _save(data):
    # Keep the file small: drop comment records older than 30 days.
    cutoff = time.time() - 30 * 24 * 3600
    data["comments"] = {k: v for k, v in data["comments"].items() if v.get("created_at", 0) > cutoff}
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _file())


def save_media_link(media_id, short_link, **details):
    record = {"short_link": short_link, "created_at": time.time(),
              **{k: v for k, v in details.items() if v}}
    db = _mongo()
    if db is not None:
        db.media.update_one({"_id": str(media_id)}, {"$set": record}, upsert=True)
        return
    with _lock:
        data = _load()
        data["media"][str(media_id)] = record
        _save(data)


def get_media_record(media_id):
    db = _mongo()
    if db is not None:
        return db.media.find_one({"_id": str(media_id)})
    with _lock:
        return _load()["media"].get(str(media_id))


def claim(key):
    """Atomically mark ``key`` (comment id or user+media) as handled.

    Returns False if it was already claimed, so each comment/user gets one DM.
    """
    db = _mongo()
    if db is not None:
        from pymongo.errors import DuplicateKeyError

        try:
            from datetime import datetime, timezone

            db.comments.insert_one({"_id": key, "created_at": datetime.now(timezone.utc)})
            return True
        except DuplicateKeyError:
            return False
    with _lock:
        data = _load()
        if key in data["comments"]:
            return False
        data["comments"][key] = {"created_at": time.time()}
        _save(data)
        return True


def release(key):
    """Undo a claim after a failed send so a retry/new comment can succeed."""
    db = _mongo()
    if db is not None:
        db.comments.delete_one({"_id": key})
        return
    with _lock:
        data = _load()
        if data["comments"].pop(key, None) is not None:
            _save(data)
