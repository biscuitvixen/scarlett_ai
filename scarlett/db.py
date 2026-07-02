from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_timezones (
    user_id INTEGER PRIMARY KEY,
    timezone TEXT NOT NULL
)
"""


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    @classmethod
    async def open(cls, path: str) -> "Database":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        await conn.execute(SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self.conn.close()

    async def get_timezone(self, user_id: int) -> str | None:
        async with self.conn.execute(
            "SELECT timezone FROM user_timezones WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def set_timezone(self, user_id: int, timezone: str) -> None:
        await self.conn.execute(
            "INSERT INTO user_timezones (user_id, timezone) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone",
            (user_id, timezone),
        )
        await self.conn.commit()
