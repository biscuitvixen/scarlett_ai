"""Turns time phrases in chat into Discord timestamp markup.

<t:unix:F> renders as an absolute time in each viewer's own timezone and
<t:unix:R> as a relative one, so "friday at 7pm" becomes unambiguous for
the whole server. Parsing lives in scarlett.timeparse; this cog handles
the Discord side and the per-user timezone registry.
"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

import discord
from discord import app_commands
from discord.ext import commands

from ..timeparse import TIME_OF_DAY, extract_times

# seconds between "set your timezone" nags per user
PROMPT_COOLDOWN = 3600


class Timestamps(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.zones = sorted(available_timezones())
        self.zone_set = set(self.zones)
        self.last_prompted: dict[int, float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content:
            return
        # cheap gate so most messages never touch the db
        match = TIME_OF_DAY.search(message.content)
        if "<t:" in message.content or not match:
            return

        tz_name = await self.bot.db.get_timezone(message.author.id)
        if tz_name is None:
            await self._prompt_for_timezone(message, match.group(0))
            return

        matches = extract_times(message.content, ZoneInfo(tz_name))
        if not matches:
            return
        lines = []
        for m in matches:
            unix = int(m.when.timestamp())
            lines.append(f'"{m.phrase}" is <t:{unix}:F> (<t:{unix}:R>)')
        await message.reply(
            "\n".join(lines),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _prompt_for_timezone(
        self, message: discord.Message, phrase: str
    ) -> None:
        now = time.monotonic()
        last = self.last_prompted.get(message.author.id)
        if last is not None and now - last < PROMPT_COOLDOWN:
            return
        self.last_prompted[message.author.id] = now
        # reply() pings the author by default, which is wanted here
        await message.reply(
            f'"{phrase}" looks like a time! I don\'t know your timezone yet '
            "though. Set it with /tz and I'll sort the conversions for everyone."
        )

    @app_commands.command(
        description="Set your timezone so time phrases convert correctly"
    )
    @app_commands.describe(timezone="IANA timezone name, e.g. Europe/London")
    async def tz(self, interaction: discord.Interaction, timezone: str) -> None:
        if timezone not in self.zone_set:
            await interaction.response.send_message(
                f"Hmm, '{timezone}' isn't an IANA timezone name. "
                "Try the autocomplete, something like Europe/London.",
                ephemeral=True,
            )
            return
        await self.bot.db.set_timezone(interaction.user.id, timezone)
        local = datetime.now(ZoneInfo(timezone)).strftime("%H:%M")
        await interaction.response.send_message(
            f"All set, your timezone's {timezone}. "
            f"That puts your local time around {local}, if that's off just pick again.",
            ephemeral=True,
        )

    @tz.autocomplete("timezone")
    async def tz_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        needle = current.lower()
        hits = [z for z in self.zones if needle in z.lower()]
        return [app_commands.Choice(name=z, value=z) for z in hits[:25]]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Timestamps(bot))
