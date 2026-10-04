import os
import sqlite3
import time
from pathlib import Path


DATABASE_PATH = Path(
    os.getenv(
        "INSTAGRAM_LINK_DB",
        str(Path(__file__).resolve().parent / "data" / "instagram_links.sqlite3"),
    )
)
COMMENT_CLAIM_TTL_SECONDS = 15 * 60


def _connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS media_links (
            media_id TEXT PRIMARY KEY,
            short_link TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS processed_comments (
            comment_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """
    )
    return connection


def store_media_link(media_id, short_link):
    if not media_id or not short_link:
        raise ValueError("Both Instagram media ID and short link are required.")

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO media_links (media_id, short_link, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(media_id) DO UPDATE SET
                short_link = excluded.short_link,
                created_at = excluded.created_at
            """,
            (str(media_id), short_link, int(time.time())),
        )


def get_media_link(media_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT short_link FROM media_links WHERE media_id = ?",
            (str(media_id),),
        ).fetchone()
    return row["short_link"] if row else None


def claim_comment(comment_id, now=None):
    if not comment_id:
        raise ValueError("Instagram comment ID is required.")

    timestamp = int(time.time() if now is None else now)
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, updated_at FROM processed_comments WHERE comment_id = ?",
            (str(comment_id),),
        ).fetchone()

        if row and (
            row["status"] == "sent"
            or (
                row["status"] == "processing"
                and timestamp - row["updated_at"] < COMMENT_CLAIM_TTL_SECONDS
            )
        ):
            return False

        connection.execute(
            """
            INSERT INTO processed_comments (comment_id, status, updated_at)
            VALUES (?, 'processing', ?)
            ON CONFLICT(comment_id) DO UPDATE SET
                status = 'processing',
                updated_at = excluded.updated_at
            """,
            (str(comment_id), timestamp),
        )
    return True


def mark_comment_sent(comment_id):
    with _connect() as connection:
        result = connection.execute(
            """
            UPDATE processed_comments
            SET status = 'sent', updated_at = ?
            WHERE comment_id = ?
            """,
            (int(time.time()), str(comment_id)),
        )
        if result.rowcount != 1:
            raise RuntimeError("Could not mark Instagram comment as processed.")


def mark_comment_failed(comment_id):
    with _connect() as connection:
        connection.execute(
            """
            UPDATE processed_comments
            SET status = 'failed', updated_at = ?
            WHERE comment_id = ?
            """,
            (int(time.time()), str(comment_id)),
        )
