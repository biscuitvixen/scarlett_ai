"""Scarlett's voice in chat.

Replies when mentioned or replied to, and occasionally interjects on her
own, but only in whitelisted guilds (CHAT_GUILD_IDS). The personality
lives in personality.md, which the LLM wrapper rereads on every call, so
it can be edited live without a rebuild.
"""

import asyncio
import logging
import random
import time

import discord
from discord.ext import commands

from ..ratelimit import RateLimiter

log = logging.getLogger(__name__)

HISTORY_LIMIT = 15
INTERJECT_CHANCE = 0.02
INTERJECT_COOLDOWN = 600  # seconds per channel
FALLBACK = "brain's not switched on right now, someone poke the gpu"
# said once when someone's being throttled, then she goes quiet for them
THROTTLE_LINES = ("easy, one at a time", "give me a sec, yeah?", "hang on")


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_interject: dict[int, float] = {}
        s = bot.settings
        self.limiter = RateLimiter(s.chat_user_cooldown, s.chat_user_hourly_cap)
        self.sem = asyncio.Semaphore(s.chat_max_concurrent)
        # users who've already had the one-time notice this burst
        self.throttle_notified: set[int] = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if (
            message.guild is None
            or message.guild.id not in self.bot.settings.chat_guilds
        ):
            return

        # a mention always gets a reply, even if the message is just an
        # attachment with no text
        mentioned = await self._addressed_to_me(message)
        if not mentioned and not (
            message.content and self._wants_to_interject(message)
        ):
            return

        # owners bypass every limit, everyone else gets throttled. a mention
        # while throttled earns one terse notice then silence, an interjection
        # she'd have made just gets dropped
        user_id = message.author.id
        owner = user_id in self.bot.settings.owners
        if not owner and not self.limiter.allowed(user_id, time.monotonic()):
            if mentioned and user_id not in self.throttle_notified:
                self.throttle_notified.add(user_id)
                await message.reply(
                    random.choice(THROTTLE_LINES), mention_author=False
                )
            return
        self.throttle_notified.discard(user_id)

        transcript = await self._transcript(message.channel)
        text = FALLBACK
        try:
            # the semaphore serialises generations so a burst queues instead
            # of dogpiling the gpu
            async with self.sem, message.channel.typing():
                text = await self.bot.llm.chat_reply(
                    transcript, self.bot.user.display_name
                ) or FALLBACK
        except Exception:
            log.exception("llm request failed")

        if mentioned:
            await message.reply(text[:2000], mention_author=False)
        elif text is not FALLBACK:
            await message.channel.send(text[:2000])
            self.last_interject[message.channel.id] = time.monotonic()
        else:
            return

        if not owner:
            self.limiter.record(user_id, time.monotonic())

    async def _addressed_to_me(self, message: discord.Message) -> bool:
        if self.bot.user in message.mentions:
            return True
        if message.reference is None:
            return False
        ref = message.reference.resolved
        if ref is None and message.reference.message_id:
            # replied-to message wasn't in the cache
            try:
                ref = await message.channel.fetch_message(
                    message.reference.message_id
                )
            except discord.HTTPException:
                return False
        return isinstance(ref, discord.Message) and ref.author == self.bot.user

    def _wants_to_interject(self, message: discord.Message) -> bool:
        if random.random() > INTERJECT_CHANCE:
            return False
        last = self.last_interject.get(message.channel.id)
        return last is None or time.monotonic() - last > INTERJECT_COOLDOWN

    async def _transcript(self, channel: discord.abc.Messageable) -> str:
        line_cap = self.bot.settings.chat_line_char_cap
        total_cap = self.bot.settings.chat_transcript_char_cap
        lines = []
        total = 0
        # history comes newest first, so build from the newest and stop once
        # the budget is full to keep the most recent messages
        async for m in channel.history(limit=HISTORY_LIMIT):
            if not m.content:
                continue
            line = f"{m.author.display_name}: {m.clean_content}"
            if len(line) > line_cap:
                line = line[:line_cap] + "..."
            if lines and total + len(line) > total_cap:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(reversed(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
