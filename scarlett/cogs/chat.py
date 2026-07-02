"""Personality chat, not implemented yet.

The plan: an openai client pointed at LLM_BASE_URL (the vllm container),
a system prompt defining the bot's personality, and a reply policy so it
answers when mentioned and occasionally interjects on its own, with
per-channel rate limiting so it does not get annoying.
"""

import discord
from discord.ext import commands


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # LLM reply logic goes here.


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
