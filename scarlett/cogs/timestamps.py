"""Time coordination, not implemented yet.

The plan: watch messages for time phrases ("friday at 7pm"), resolve them
against the author's timezone, and reply with Discord timestamp markup
(<t:unix:F> plus <t:unix:R>) so everyone sees their own local time.

Parsing is deterministic first: a cheap regex prefilter, then dateparser.
The LLM is only a fallback for fuzzy phrasing the parser cannot handle.
Discord does not expose user timezones, so /tz stores one per user in
SQLite via aiosqlite.
"""

import discord
from discord import app_commands
from discord.ext import commands


class Timestamps(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Time phrase detection goes here.

    @app_commands.command(description="Set your timezone, e.g. Europe/London")
    async def tz(self, interaction: discord.Interaction, timezone: str) -> None:
        await interaction.response.send_message(
            "Timezones are not wired up yet.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Timestamps(bot))
