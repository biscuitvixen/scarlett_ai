from __future__ import annotations

from pathlib import Path

import aiosqlite

from .roles import Panel, PanelEntry, PanelMode

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_timezones (
    user_id INTEGER PRIMARY KEY,
    timezone TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_panels (
    guild_id   INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    mode       TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    body       TEXT    NOT NULL DEFAULT '',
    colour     INTEGER,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS role_panel_entries (
    guild_id INTEGER NOT NULL,
    name     TEXT    NOT NULL,
    role_id  INTEGER NOT NULL,
    label    TEXT    NOT NULL,
    emoji    TEXT,
    position INTEGER NOT NULL,
    PRIMARY KEY (guild_id, name, role_id),
    FOREIGN KEY (guild_id, name) REFERENCES role_panels(guild_id, name)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS role_panels_by_message
    ON role_panels(message_id);
"""

PANEL_COLUMNS = "guild_id, name, channel_id, message_id, mode, title, body, colour"

# columns added after a table first shipped. CREATE TABLE IF NOT EXISTS does
# nothing to a table that already exists, so a database made before one of
# these was introduced needs it added on the way in
ADDED_COLUMNS = [
    ("role_panels", "colour", "INTEGER"),
]


def _panel(row: aiosqlite.Row, entries: tuple[PanelEntry, ...]) -> Panel:
    return Panel(
        guild_id=row[0],
        name=row[1],
        channel_id=row[2],
        message_id=row[3],
        mode=PanelMode(row[4]),
        title=row[5],
        body=row[6],
        colour=row[7],
        entries=entries,
    )


async def _add_missing_columns(conn: aiosqlite.Connection) -> None:
    """Bring an older database up to the current column set.

    Kept as a list of additions checked against the live table rather than
    a version counter, because every change so far is a nullable column on
    a table that is otherwise unchanged. Anything needing rows rewritten
    or a column dropped wants a real migration ledger instead.
    """
    for table, column, decl in ADDED_COLUMNS:
        async with conn.execute(f"PRAGMA table_info({table})") as cur:
            present = {row[1] for row in await cur.fetchall()}
        if column not in present:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    @classmethod
    async def open(cls, path: str) -> "Database":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        # per-connection and off by default, so without it the panel entry
        # cascade silently leaves orphaned rows behind
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(SCHEMA)
        await _add_missing_columns(conn)
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

    # role panels. these satisfy scarlett.roles.PanelStore structurally, so
    # the roles cog never sees this class

    async def get_panel(self, guild_id: int, name: str) -> Panel | None:
        async with self.conn.execute(
            f"SELECT {PANEL_COLUMNS} FROM role_panels WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return _panel(row, await self._entries(guild_id, name))

    async def list_panels(self, guild_id: int) -> list[Panel]:
        async with self.conn.execute(
            f"SELECT {PANEL_COLUMNS} FROM role_panels WHERE guild_id = ? ORDER BY name",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_panel(r, await self._entries(guild_id, r[1])) for r in rows]

    async def panel_for_message(self, message_id: int) -> Panel | None:
        async with self.conn.execute(
            f"SELECT {PANEL_COLUMNS} FROM role_panels WHERE message_id = ?",
            (message_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return _panel(row, await self._entries(row[0], row[1]))

    async def panels_with_role(self, guild_id: int, role_id: int) -> list[Panel]:
        async with self.conn.execute(
            "SELECT name FROM role_panel_entries WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        ) as cur:
            names = [r[0] for r in await cur.fetchall()]
        panels = [await self.get_panel(guild_id, n) for n in names]
        return [p for p in panels if p is not None]

    async def save_panel(self, panel: Panel) -> None:
        """Write the panel and replace its entries wholesale.

        Entries are rewritten rather than diffed because a panel is at
        most 25 rows and positions renumber on every edit anyway.
        """
        await self.conn.execute(
            f"INSERT INTO role_panels ({PANEL_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, name) DO UPDATE SET "
            "channel_id = excluded.channel_id, "
            "message_id = excluded.message_id, "
            "mode = excluded.mode, "
            "title = excluded.title, "
            "body = excluded.body, "
            "colour = excluded.colour",
            (
                panel.guild_id,
                panel.name,
                panel.channel_id,
                panel.message_id,
                panel.mode.value,
                panel.title,
                panel.body,
                panel.colour,
            ),
        )
        await self.conn.execute(
            "DELETE FROM role_panel_entries WHERE guild_id = ? AND name = ?",
            (panel.guild_id, panel.name),
        )
        await self.conn.executemany(
            "INSERT INTO role_panel_entries "
            "(guild_id, name, role_id, label, emoji, position) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    panel.guild_id,
                    panel.name,
                    e.role_id,
                    e.label,
                    e.emoji,
                    e.position,
                )
                for e in panel.entries
            ],
        )
        await self.conn.commit()

    async def delete_panel(self, guild_id: int, name: str) -> None:
        await self.conn.execute(
            "DELETE FROM role_panels WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )
        await self.conn.commit()

    async def set_message_id(
        self, guild_id: int, name: str, message_id: int | None
    ) -> None:
        await self.conn.execute(
            "UPDATE role_panels SET message_id = ? WHERE guild_id = ? AND name = ?",
            (message_id, guild_id, name),
        )
        await self.conn.commit()

    async def _entries(self, guild_id: int, name: str) -> tuple[PanelEntry, ...]:
        async with self.conn.execute(
            "SELECT position, role_id, label, emoji FROM role_panel_entries "
            "WHERE guild_id = ? AND name = ? ORDER BY position",
            (guild_id, name),
        ) as cur:
            rows = await cur.fetchall()
        return tuple(PanelEntry(r[0], r[1], r[2], r[3]) for r in rows)
