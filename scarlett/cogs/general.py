import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(description="Check that the bot is alive")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Still here, {self.bot.latency * 1000:.0f}ms."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
