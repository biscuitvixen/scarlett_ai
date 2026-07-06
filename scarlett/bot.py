import logging

import discord
import wavelink
from discord.ext import commands

from .config import Settings
from .db import Database
from .llm import LLM

log = logging.getLogger(__name__)

# always loaded; the chat cog is added on top only when the LLM is enabled
COGS = [
    "scarlett.cogs.general",
    "scarlett.cogs.timestamps",
    "scarlett.cogs.music",
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

    async def setup_hook(self) -> None:
        self.db = await Database.open(self.settings.db_path)
        cogs = COGS + ["scarlett.cogs.chat"] if self.settings.llm_enabled else COGS
        for cog in cogs:
            await self.load_extension(cog)
            log.info("loaded %s", cog)

        # Connect to lavalink for music. Wrapped so an unreachable node just
        # disables playback instead of taking the whole bot down, same spirit
        # as the sync fallback below. wavelink.Pool is global, the music cog
        # reaches it without any extra wiring.
        try:
            node = wavelink.Node(
                uri=self.settings.lavalink_url,
                password=self.settings.lavalink_password,
            )
            await wavelink.Pool.connect(client=self, nodes=[node])
        except Exception:
            log.exception("could not connect to lavalink, music will be unavailable")

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

    async def on_ready(self) -> None:
        log.info("logged in as %s (%s)", self.user, self.user.id)

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
        await super().close()
