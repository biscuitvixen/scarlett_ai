"""Music playback backed by lavalink.

A wavelink node is connected on startup (see bot.setup_hook). /play joins the
caller's voice channel and queues whatever the link or search resolves to.
Lavalink does the decoding and streaming, the bot only manages the queue.
"""

import logging

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        log.info("lavalink node ready: %s", payload.node.identifier)

    @app_commands.command(description="Play a track from a link or search")
    @app_commands.describe(query="a url, or something to search for on youtube")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        # you have to be in a voice channel for her to know where to join
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message(
                "hop into a voice channel first", ephemeral=True
            )
            return

        # reuse the existing player if she's already in a channel, otherwise
        # join the caller's. autoplay partial just walks the queue, it won't
        # start pulling in youtube recommendations of its own
        player: wavelink.Player | None = interaction.guild.voice_client
        if player is None:
            player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            player.autoplay = wavelink.AutoPlayMode.partial

        # searching can take a moment, don't let the interaction time out
        await interaction.response.defer()

        # search raises rather than returning empty when lavalink itself
        # chokes (youtube throttling, a dead source), so catch it and reply
        # instead of leaving the deferred interaction hanging
        try:
            tracks: wavelink.Search = await wavelink.Playable.search(query)
        except wavelink.LavalinkLoadException:
            log.exception("lavalink failed to load %r", query)
            await interaction.followup.send("couldn't load that one, try another")
            return
        if not tracks:
            await interaction.followup.send("couldn't find anything for that")
            return

        if isinstance(tracks, wavelink.Playlist):
            added = await player.queue.put_wait(tracks)
            await interaction.followup.send(
                f"queued **{added}** tracks from **{tracks.name}**"
            )
        else:
            track = tracks[0]
            await player.queue.put_wait(track)
            await interaction.followup.send(f"queued **{track.title}**")

        if not player.playing:
            await player.play(player.queue.get())

    @app_commands.command(description="Skip the current track")
    async def skip(self, interaction: discord.Interaction) -> None:
        player: wavelink.Player | None = interaction.guild.voice_client
        if player is None or not player.playing:
            await interaction.response.send_message(
                "nothing's playing", ephemeral=True
            )
            return
        await player.skip(force=True)
        await interaction.response.send_message("skipped", ephemeral=True)

    @app_commands.command(description="Stop playback and clear the queue")
    async def stop(self, interaction: discord.Interaction) -> None:
        player: wavelink.Player | None = interaction.guild.voice_client
        if player is None:
            await interaction.response.send_message(
                "not playing anything", ephemeral=True
            )
            return
        player.queue.reset()
        await player.disconnect()
        await interaction.response.send_message("stopped, see you", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
