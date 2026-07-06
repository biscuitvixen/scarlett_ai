"""Writes the liveness heartbeat the container healthcheck reads.

See scarlett.health for the file it stamps and how Docker consumes it.
"""

import logging

from discord.ext import commands, tasks

from ..health import HEARTBEAT_INTERVAL, write_heartbeat

log = logging.getLogger(__name__)


class Health(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._beat.start()

    async def cog_unload(self) -> None:
        self._beat.cancel()

    @tasks.loop(seconds=HEARTBEAT_INTERVAL)
    async def _beat(self) -> None:
        # only stamp while she's actually connected. a dropped gateway clears
        # the ready event, so skipping the write lets the file go stale and the
        # healthcheck trip, instead of reporting a wedged bot as healthy
        if self.bot.is_ready() and not self.bot.is_closed():
            try:
                write_heartbeat()
            except OSError:
                log.exception("could not write heartbeat file")

    @_beat.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Health(bot))
