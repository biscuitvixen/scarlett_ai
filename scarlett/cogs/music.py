"""Music playback backed by lavalink.

A wavelink node is connected on startup (see bot.setup_hook). /play joins the
caller's voice channel and queues whatever the link or search resolves to.
Lavalink does the decoding and streaming, the bot only manages the queue.

On top of play/skip/stop there are the usual controls (pause, volume, shuffle,
loop, queue, nowplaying). She also tidies up after herself: she leaves when the
channel empties and after a stretch of nothing playing.
"""

import logging

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)


def _format_duration(ms: int) -> str:
    """Milliseconds to m:ss, or h:mm:ss once it runs past an hour."""
    total_seconds = max(0, ms) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _progress_bar(position: int, length: int, width: int = 15) -> str:
    """A little ━━●── playhead bar for the current track position."""
    if length <= 0:
        filled = 0
    else:
        filled = min(width, max(0, round(position / length * width)))
    if filled >= width:
        return "━" * width
    return "━" * filled + "●" + "─" * (width - filled - 1)


# how the three queue modes read to a human, and which one comes next when
# /loop is cycled
_LOOP_LABELS = {
    wavelink.QueueMode.normal: "off",
    wavelink.QueueMode.loop: "this track",
    wavelink.QueueMode.loop_all: "the whole queue",
}
_LOOP_NEXT = {
    wavelink.QueueMode.normal: wavelink.QueueMode.loop,
    wavelink.QueueMode.loop: wavelink.QueueMode.loop_all,
    wavelink.QueueMode.loop_all: wavelink.QueueMode.normal,
}


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        log.info("lavalink node ready: %s", payload.node.identifier)

    async def _active_player(
        self, interaction: discord.Interaction, *, same_channel: bool = True
    ) -> wavelink.Player | None:
        """The guild's player, or None after replying with why not.

        Control commands pass same_channel=True so only people actually in the
        channel with her can push buttons; read-only commands (queue, now
        playing) pass False.
        """
        player: wavelink.Player | None = interaction.guild.voice_client
        if player is None:
            await interaction.response.send_message(
                "Nothing's playing right now.", ephemeral=True
            )
            return None
        if same_channel:
            voice = (
                interaction.user.voice
                if isinstance(interaction.user, discord.Member)
                else None
            )
            if voice is None or voice.channel != player.channel:
                await interaction.response.send_message(
                    "You've got to be in my voice channel for that one.",
                    ephemeral=True,
                )
                return None
        return player

    @app_commands.command(description="Play a track from a link or search")
    @app_commands.describe(query="a url, or something to search for on youtube")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        # you have to be in a voice channel for her to know where to join
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message(
                "Hop into a voice channel first and I'll join you.", ephemeral=True
            )
            return

        # reuse the existing player if she's already in a channel, otherwise
        # join the caller's. autoplay partial just walks the queue, it won't
        # start pulling in youtube recommendations of its own. the idle timeout
        # is what makes her leave once the queue runs dry
        player: wavelink.Player | None = interaction.guild.voice_client
        if player is None:
            player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            player.autoplay = wavelink.AutoPlayMode.partial
            player.inactive_timeout = self.bot.settings.music_idle_timeout

        # searching can take a moment, don't let the interaction time out
        await interaction.response.defer()

        # search raises rather than returning empty when lavalink itself
        # chokes (youtube throttling, a dead source), so catch it and reply
        # instead of leaving the deferred interaction hanging
        try:
            tracks: wavelink.Search = await wavelink.Playable.search(query)
        except wavelink.LavalinkLoadException:
            log.exception("lavalink failed to load %r", query)
            await interaction.followup.send("Couldn't load that one, sorry. Try another?")
            return
        if not tracks:
            await interaction.followup.send("Couldn't find anything for that, sorry.")
            return

        if isinstance(tracks, wavelink.Playlist):
            added = await player.queue.put_wait(tracks)
            await interaction.followup.send(
                f"Queued **{added}** tracks from **{tracks.name}**."
            )
        else:
            track = tracks[0]
            await player.queue.put_wait(track)
            await interaction.followup.send(f"Queued **{track.title}**.")

        if not player.playing:
            await player.play(player.queue.get())

    @app_commands.command(description="Skip the current track")
    async def skip(self, interaction: discord.Interaction) -> None:
        player = await self._active_player(interaction)
        if player is None:
            return
        if not player.playing:
            await interaction.response.send_message(
                "Nothing's playing right now.", ephemeral=True
            )
            return
        await player.skip(force=True)
        await interaction.response.send_message("Skipped it.", ephemeral=True)

    @app_commands.command(description="Pause or resume playback")
    async def pause(self, interaction: discord.Interaction) -> None:
        player = await self._active_player(interaction)
        if player is None:
            return
        await player.pause(not player.paused)
        await interaction.response.send_message(
            "Paused." if player.paused else "Back on.", ephemeral=True
        )

    @app_commands.command(description="Set the playback volume")
    @app_commands.describe(level="0 to 100")
    async def volume(
        self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]
    ) -> None:
        player = await self._active_player(interaction)
        if player is None:
            return
        await player.set_volume(level)
        await interaction.response.send_message(
            f"Volume's at {level} now.", ephemeral=True
        )

    @app_commands.command(description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = await self._active_player(interaction)
        if player is None:
            return
        if player.queue.count < 2:
            await interaction.response.send_message(
                "Not enough in the queue to shuffle.", ephemeral=True
            )
            return
        player.queue.shuffle()
        await interaction.response.send_message("Shuffled the queue.", ephemeral=True)

    @app_commands.command(description="Cycle looping: off, track, whole queue")
    async def loop(self, interaction: discord.Interaction) -> None:
        player = await self._active_player(interaction)
        if player is None:
            return
        player.queue.mode = _LOOP_NEXT[player.queue.mode]
        if player.queue.mode == wavelink.QueueMode.normal:
            message = "Loop's off now."
        else:
            message = f"Looping {_LOOP_LABELS[player.queue.mode]} now."
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(description="Show the queue")
    async def queue(self, interaction: discord.Interaction) -> None:
        player = await self._active_player(interaction, same_channel=False)
        if player is None:
            return
        if player.current is None and player.queue.is_empty:
            await interaction.response.send_message(
                "The queue's empty.", ephemeral=True
            )
            return

        embed = discord.Embed(title="Queue", color=discord.Color.blurple())
        if player.current is not None:
            embed.add_field(
                name="Now playing", value=f"**{player.current.title}**", inline=False
            )
        upcoming = list(player.queue)[:10]
        if upcoming:
            lines = [f"{i}. {t.title}" for i, t in enumerate(upcoming, 1)]
            extra = player.queue.count - len(upcoming)
            if extra > 0:
                lines.append(f"…and {extra} more")
            embed.add_field(name="Up next", value="\n".join(lines), inline=False)
        embed.set_footer(
            text=f"Loop: {_LOOP_LABELS[player.queue.mode]} · Volume: {player.volume}"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Show the current track")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player = await self._active_player(interaction, same_channel=False)
        if player is None:
            return
        track = player.current
        if track is None:
            await interaction.response.send_message(
                "Nothing's playing right now.", ephemeral=True
            )
            return
        bar = _progress_bar(player.position, track.length)
        pos = _format_duration(player.position)
        total = _format_duration(track.length)
        state = "⏸" if player.paused else "▶"
        embed = discord.Embed(
            title=track.title,
            url=track.uri,
            description=f"{state} {bar}\n`{pos} / {total}`",
            color=discord.Color.blurple(),
        )
        if track.author:
            embed.set_author(name=track.author)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Stop playback and clear the queue")
    async def stop(self, interaction: discord.Interaction) -> None:
        player = await self._active_player(interaction)
        if player is None:
            return
        player.queue.reset()
        await player.disconnect()
        await interaction.response.send_message(
            "Stopped, see you around.", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        # fired once nothing has played for settings.music_idle_timeout seconds
        await player.disconnect()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # leave once she's the only one left, no sense playing to an empty room.
        # ignore bots (including her own moves, where the player is gone anyway)
        if member.bot:
            return
        player: wavelink.Player | None = member.guild.voice_client
        if player is None or player.channel is None:
            return
        if not any(not m.bot for m in player.channel.members):
            player.queue.reset()
            await player.disconnect()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
