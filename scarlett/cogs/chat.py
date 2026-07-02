"""Scarlett's voice in chat.

Replies when mentioned or replied to, and occasionally interjects on her
own, but only in whitelisted guilds (CHAT_GUILD_IDS). The personality
lives in personality.md, which the LLM wrapper rereads on every call, so
it can be edited live without a rebuild.
"""

import logging
import random
import time

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

HISTORY_LIMIT = 15
INTERJECT_CHANCE = 0.02
INTERJECT_COOLDOWN = 600  # seconds per channel
FALLBACK = "brain's not switched on right now, someone poke the gpu"


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_interject: dict[int, float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content:
            return
        if (
            message.guild is None
            or message.guild.id not in self.bot.settings.chat_guilds
        ):
            return

        mentioned = self._addressed_to_me(message)
        if not mentioned and not self._wants_to_interject(message):
            return

        transcript = await self._transcript(message.channel)
        try:
            async with message.channel.typing():
                text = await self.bot.llm.chat_reply(
                    transcript, self.bot.user.display_name
                )
        except Exception:
            log.exception("llm request failed")
            if mentioned:
                await message.reply(FALLBACK, mention_author=False)
            return
        if not text:
            return

        if mentioned:
            await message.reply(text[:2000], mention_author=False)
        else:
            await message.channel.send(text[:2000])
            self.last_interject[message.channel.id] = time.monotonic()

    def _addressed_to_me(self, message: discord.Message) -> bool:
        if self.bot.user in message.mentions:
            return True
        ref = message.reference.resolved if message.reference else None
        return isinstance(ref, discord.Message) and ref.author == self.bot.user

    def _wants_to_interject(self, message: discord.Message) -> bool:
        if random.random() > INTERJECT_CHANCE:
            return False
        last = self.last_interject.get(message.channel.id)
        return last is None or time.monotonic() - last > INTERJECT_COOLDOWN

    async def _transcript(self, channel: discord.abc.Messageable) -> str:
        lines = []
        async for m in channel.history(limit=HISTORY_LIMIT):
            if not m.content:
                continue
            lines.append(f"{m.author.display_name}: {m.clean_content}")
        return "\n".join(reversed(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
