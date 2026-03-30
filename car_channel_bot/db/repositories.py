from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

UTC = timezone.utc


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class Database:
    def __init__(self, path: str) -> None:
        self._path = path

    async def connect(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        from car_channel_bot.db.schema import SCHEMA_SQL

        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()

    async def close(self) -> None:
        await self._db.close()

    async def is_listing_seen_recently(self, url: str, ttl_days: int) -> bool:
        cutoff = (datetime.now(tz=UTC) - timedelta(days=ttl_days)).isoformat()
        cur = await self._db.execute(
            "SELECT 1 FROM listings_seen WHERE url_normalized = ? AND seen_at > ?",
            (url, cutoff),
        )
        row = await cur.fetchone()
        return row is not None

    async def mark_listing_seen(self, url: str) -> None:
        await self._db.execute(
            """
            INSERT INTO listings_seen(url_normalized, seen_at) VALUES(?, ?)
            ON CONFLICT(url_normalized) DO UPDATE SET seen_at = excluded.seen_at
            """,
            (url, _now_iso()),
        )
        await self._db.commit()

    async def prune_old_listings(self, ttl_days: int) -> None:
        cutoff = (datetime.now(tz=UTC) - timedelta(days=ttl_days)).isoformat()
        await self._db.execute("DELETE FROM listings_seen WHERE seen_at < ?", (cutoff,))
        await self._db.commit()

    async def insert_post(
        self,
        *,
        channel_message_id: int | None,
        source: str,
        admin_id: int | None,
        listing_url: str | None = None,
        caption: str = "",
    ) -> int:
        cap = caption if caption.strip() else "."
        cur = await self._db.execute(
            """
            INSERT INTO posts(channel_message_id, mode, listing_url, caption, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (channel_message_id, source, listing_url, cap, _now_iso()),
        )
        await self._db.commit()
        return int(cur.lastrowid)

    async def insert_event(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        await self._db.execute(
            "INSERT INTO events(event_type, post_id, details, created_at) VALUES(?, NULL, ?, ?)",
            (kind, json.dumps(payload or {}), _now_iso()),
        )
        await self._db.commit()

    async def create_auto_batch(
        self,
        *,
        admin_id: int,
        filters: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> str:
        batch_id = str(uuid.uuid4())
        await self._db.execute(
            """
            INSERT INTO auto_batches(id, admin_id, status, filters_json, items_json, created_at)
            VALUES(?, ?, 'pending', ?, ?, ?)
            """,
            (batch_id, admin_id, json.dumps(filters), json.dumps(items), _now_iso()),
        )
        await self._db.commit()
        return batch_id

    async def get_auto_batch(self, batch_id: str) -> dict[str, Any] | None:
        cur = await self._db.execute("SELECT * FROM auto_batches WHERE id = ?", (batch_id,))
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)

    async def update_auto_batch_status(self, batch_id: str, status: str) -> None:
        await self._db.execute(
            "UPDATE auto_batches SET status = ? WHERE id = ?",
            (status, batch_id),
        )
        await self._db.commit()

    async def update_auto_batch_items(self, batch_id: str, items: list[dict[str, Any]]) -> None:
        await self._db.execute(
            "UPDATE auto_batches SET items_json = ? WHERE id = ?",
            (json.dumps(items), batch_id),
        )
        await self._db.commit()

    async def stats_summary(self) -> dict[str, Any]:
        cur = await self._db.execute("SELECT COUNT(*) AS c FROM posts")
        posts = (await cur.fetchone())["c"]
        cur = await self._db.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_type = 'auto_approved'"
        )
        approved = (await cur.fetchone())["c"]
        return {"posts_total": posts, "auto_approved": approved}
