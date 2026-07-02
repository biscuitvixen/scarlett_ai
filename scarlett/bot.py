import logging

import discord
from discord.ext import commands

from .config import Settings
from .db import Database

log = logging.getLogger(__name__)

COGS = [
    "scarlett.cogs.general",
    "scarlett.cogs.chat",
    "scarlett.cogs.timestamps",
    "scarlett.cogs.music",
]


class Scarlett(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.db: Database | None = None

    async def setup_hook(self) -> None:
        self.db = await Database.open(self.settings.db_path)
        for cog in COGS:
            await self.load_extension(cog)
            log.info("loaded %s", cog)

        # Guild-scoped sync shows new slash commands immediately.
        # Global sync can take up to an hour, so use GUILD_ID during dev.
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("logged in as %s (%s)", self.user, self.user.id)

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
        await super().close()
