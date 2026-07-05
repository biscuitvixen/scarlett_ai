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

    @app_commands.command(description="See what I can do")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="What I'm good for",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Music",
            value=(
                "`/play` a link or a search and I'll join your voice channel\n"
                "`/skip` · `/stop` · `/pause` · `/volume` · `/shuffle` · `/loop`\n"
                "`/queue` · `/nowplaying`\n"
                "Sources: YouTube, SoundCloud, Bandcamp, Twitch, Vimeo, and "
                "direct audio or radio links. Plain searches use YouTube."
            ),
            inline=False,
        )
        embed.add_field(
            name="Timestamps",
            value=(
                "`/tz` to set your timezone, then I'll turn times like "
                '"friday at 7pm" into everyone\'s own local time.'
            ),
            inline=False,
        )
        # shown even when the llm is off, the wording hints she might be quiet
        embed.add_field(
            name="If I'm feeling talkative",
            value=(
                "When my brain's switched on, mention me or reply and I'll "
                "chat back, and I'll pipe up on my own now and then too."
            ),
            inline=False,
        )
        embed.add_field(
            name="Bits and bobs",
            value="`/ping` to check I'm awake · `/help` for this",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
