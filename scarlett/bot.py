import asyncio
import logging

import discord
import wavelink
from discord.ext import commands

from .config import Settings
from .db import Database
from .llm import LLM

log = logging.getLogger(__name__)

# always loaded. music and chat each need a backing service, so they are
# added only when theirs is switched on
COGS = [
    "scarlett.cogs.general",
    "scarlett.cogs.timestamps",
    "scarlett.cogs.health",
]


class Scarlett(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.db: Database | None = None
        self.llm: LLM | None = LLM(settings) if settings.llm_enabled else None
        self.lavalink_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self.db = await Database.open(self.settings.db_path)
        cogs = list(COGS)
        if self.settings.music_enabled:
            cogs.append("scarlett.cogs.music")
        if self.settings.llm_enabled:
            cogs.append("scarlett.cogs.chat")
        for cog in cogs:
            await self.load_extension(cog)
            log.info("loaded %s", cog)

        # Connect to lavalink for music, in the background: wavelink retries
        # an unreachable node forever, and awaiting that here would hold up
        # setup_hook, leaving the bot logged in but never ready and with no
        # commands synced. Off to one side, an unreachable node just disables
        # playback. wavelink.Pool is global, the music cog reaches it without
        # any extra wiring.
        if self.settings.music_enabled:
            self.lavalink_task = asyncio.create_task(self._connect_lavalink())

        # Guild-scoped sync shows new slash commands immediately.
        # Global sync can take up to an hour, so use GUILD_ID during dev.
        try:
            if self.settings.guild_id:
                guild = discord.Object(id=self.settings.guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
        except discord.Forbidden:
            # Usually means the bot was invited without the
            # applications.commands scope, keep running so chat features
            # still work and print the fix
            log.error(
                "cannot register slash commands in guild %s, reinvite with: "
                "https://discord.com/oauth2/authorize?client_id=%s"
                "&scope=bot+applications.commands&permissions=277062455360",
                self.settings.guild_id,
                self.application_id,
            )

    async def _connect_lavalink(self) -> None:
        try:
            node = wavelink.Node(
                uri=self.settings.lavalink_url,
                password=self.settings.lavalink_password,
            )
            await wavelink.Pool.connect(client=self, nodes=[node])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("could not connect to lavalink, music will be unavailable")

    async def on_ready(self) -> None:
        log.info("logged in as %s (%s)", self.user, self.user.id)

    async def close(self) -> None:
        if self.lavalink_task is not None:
            self.lavalink_task.cancel()
        if self.db is not None:
            await self.db.close()
        await super().close()
