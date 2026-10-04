import os
import time

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError


COMMENT_CLAIM_TTL_SECONDS = 15 * 60
_CLIENT = None
_DATABASE = None


def _database():
    global _CLIENT, _DATABASE
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("Set MONGODB_URI in the webhook service environment.")

    if _CLIENT is None:
        _CLIENT = MongoClient(uri, serverSelectionTimeoutMS=10_000)

    if _DATABASE is None:
        database_name = os.getenv("MONGODB_DATABASE") or "jobhunter"
        _DATABASE = _CLIENT[database_name]
        _DATABASE.media_links.create_index("media_id", unique=True)
        _DATABASE.processed_comments.create_index("comment_id", unique=True)

    return _DATABASE


def store_media_link(media_id, short_link):
    if not media_id or not short_link:
        raise ValueError("Both Instagram media ID and short link are required.")

    _database().media_links.update_one(
        {"media_id": str(media_id)},
        {
            "$set": {
                "short_link": short_link,
                "created_at": int(time.time()),
            }
        },
        upsert=True,
    )


def get_media_link(media_id):
    record = _database().media_links.find_one(
        {"media_id": str(media_id)},
        {"_id": 0, "short_link": 1},
    )
    return record["short_link"] if record else None


def claim_comment(comment_id, now=None):
    if not comment_id:
        raise ValueError("Instagram comment ID is required.")

    timestamp = int(time.time() if now is None else now)
    key = {"comment_id": str(comment_id)}
    collection = _database().processed_comments

    claimed = collection.find_one_and_update(
        {
            **key,
            "$or": [
                {"status": "failed"},
                {
                    "status": "processing",
                    "updated_at": {"$lte": timestamp - COMMENT_CLAIM_TTL_SECONDS},
                },
            ],
        },
        {"$set": {"status": "processing", "updated_at": timestamp}},
        return_document=ReturnDocument.AFTER,
    )
    if claimed:
        return True

    try:
        collection.insert_one({
            **key,
            "status": "processing",
            "updated_at": timestamp,
        })
        return True
    except DuplicateKeyError:
        return False


def mark_comment_sent(comment_id):
    result = _database().processed_comments.update_one(
        {"comment_id": str(comment_id)},
        {"$set": {"status": "sent", "updated_at": int(time.time())}},
    )
    if result.matched_count != 1:
        raise RuntimeError("Could not mark Instagram comment as processed.")


def mark_comment_failed(comment_id):
    _database().processed_comments.update_one(
        {"comment_id": str(comment_id)},
        {"$set": {"status": "failed", "updated_at": int(time.time())}},
    )
