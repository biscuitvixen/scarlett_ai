"""Music playback, not implemented yet.

The plan: connect a wavelink node to the lavalink container on startup,
then /play joins the caller's voice channel and queues whatever the link
resolves to. Lavalink does the decoding and streaming, the bot only
manages the queue.
"""

import discord
from discord import app_commands
from discord.ext import commands


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(description="Play audio from a link")
    async def play(self, interaction: discord.Interaction, link: str) -> None:
        await interaction.response.send_message(
            "Music is not wired up yet.", ephemeral=True
        )

    @app_commands.command(description="Skip the current track")
    async def skip(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Music is not wired up yet.", ephemeral=True
        )

    @app_commands.command(description="Stop playback and clear the queue")
    async def stop(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Music is not wired up yet.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
