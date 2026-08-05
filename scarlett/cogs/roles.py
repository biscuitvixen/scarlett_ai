"""Self-assignable roles as button panels.

Panel logic lives in scarlett.roles; this cog is the Discord side of it.
The admin surface is a /roles group gated behind Manage Roles, and the
member-facing side is buttons on a posted message.

Persistence is the interesting part. Each button's custom_id carries its
mode and role id, and DynamicItem matches it by pattern at dispatch
time, so clicks on panels posted by a long-dead process route correctly
with no view registry to rebuild and no storage read on the click path.
Storage is reached through the PanelStore protocol rather than the bot's
database, so the cog moves between bots without changes.
"""

from __future__ import annotations

import dataclasses
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from ..ephemeral import EphemeralReplies
from ..roles import (
    MAX_ENTRIES,
    MAX_LABEL,
    Panel,
    PanelEntry,
    PanelMode,
    PanelStore,
    RoleChange,
    RoleRejection,
    check_assignable,
    decode_custom_id,
    encode_custom_id,
    final_roles,
    pack_rows,
    parse_hex_colour,
    resolve_click,
)

log = logging.getLogger(__name__)

# panel names are typed into slash commands and used as storage keys, so
# they stay short and boring
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

# names the slash command group and, because GroupCog takes its cog name
# from the same argument, the cog itself. button callbacks look the cog up
# by it to reach the shared reply tracker, so the two must not drift apart
COG_NAME = "roles"

# each rejection names the fix rather than the rule, because the person
# reading it is usually mid-click and not holding the role hierarchy in
# their head
REJECTIONS = {
    RoleRejection.NO_MANAGE_ROLES: (
        "I don't have the Manage Roles permission in this server, so I "
        "can't hand out {role}. A server admin can grant it in Server "
        "Settings > Roles."
    ),
    RoleRejection.OUTRANKED: (
        "{role} sits above me in the role list, and I can only manage "
        "roles below my own. Drag my role above it in Server Settings > "
        "Roles and this'll work."
    ),
    RoleRejection.IS_DEFAULT: (
        "@everyone isn't something I can hand out, it's the role you get "
        "for being here at all."
    ),
    RoleRejection.IS_MANAGED: (
        "{role} is managed by an integration (a bot, or Nitro boosting), "
        "so Discord won't let anyone assign it by hand."
    ),
}

DEFAULT_COLOUR = discord.Colour.blurple()

# offered by the colour autocomplete. resolved through discord.Colour rather
# than written out here, so the values follow the library's palette instead
# of a copy of it going stale
NAMED_COLOURS = (
    "blurple",
    "green",
    "dark_green",
    "blue",
    "dark_blue",
    "red",
    "dark_red",
    "gold",
    "orange",
    "purple",
    "magenta",
    "fuchsia",
    "pink",
    "teal",
    "yellow",
    "greyple",
    "light_grey",
    "dark_grey",
)

_BAD_COLOUR = (
    "I can't read '{given}' as a colour. Pick one from the suggestions, or "
    "give me a hex code like #ff8800."
)

MODE_BLURB = {
    PanelMode.MULTI: "pick as many as you like",
    PanelMode.SINGLE: "pick one",
    PanelMode.STICKY: "click to opt in",
}


def _rejection_for(role: discord.Role) -> RoleRejection | None:
    me = role.guild.me
    return check_assignable(
        has_manage_roles=me.guild_permissions.manage_roles,
        # Role comparison ranks equal positions by id, which a bare
        # position comparison would get wrong
        bot_outranks=me.top_role > role,
        is_default=role.is_default(),
        is_managed=role.managed,
    )


def _emoji(raw: str | None) -> discord.PartialEmoji | None:
    return discord.PartialEmoji.from_str(raw) if raw else None


def resolve_colour(raw: str) -> int | None:
    """A named colour or a hex one, None if the text is neither."""
    name = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if name in NAMED_COLOURS:
        return getattr(discord.Colour, name)().value
    return parse_hex_colour(raw)


def _colour(value: int | None) -> discord.Colour:
    return DEFAULT_COLOUR if value is None else discord.Colour(value)


def colour_from_message(message: discord.Message | None) -> discord.Colour:
    """The panel's colour, taken off the panel message itself.

    Read from the message rather than storage for the same reason the
    panel's roles are: a click should not need a database round trip to
    answer.
    """
    if message is not None and message.embeds:
        posted = message.embeds[0].colour
        if posted is not None:
            return posted
    return DEFAULT_COLOUR


def panel_roles_from_message(message: discord.Message | None) -> frozenset[int]:
    """Read the panel's role ids back out of the buttons on its message.

    The message is the authoritative copy of what a panel looks like
    right now, so SINGLE mode resolves its siblings from here instead of
    a storage lookup. Components that aren't ours are skipped.
    """
    if message is None:
        return frozenset()
    ids = set()
    for row in message.components:
        for child in getattr(row, "children", ()):
            decoded = decode_custom_id(getattr(child, "custom_id", None) or "")
            if decoded is not None:
                ids.add(decoded[1])
    return frozenset(ids)


class RoleButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"rr:(?P<mode>\w+):(?P<role_id>\d+)",
):
    def __init__(
        self,
        mode: PanelMode,
        role_id: int,
        label: str,
        emoji: str | None = None,
        row: int | None = None,
    ):
        self.mode = mode
        self.role_id = role_id
        super().__init__(
            discord.ui.Button(
                label=label[:MAX_LABEL],
                emoji=_emoji(emoji),
                style=discord.ButtonStyle.secondary,
                custom_id=encode_custom_id(mode, role_id),
            ),
            row=row,
        )

    @classmethod
    def from_entry(cls, entry: PanelEntry, mode: PanelMode, row: int) -> RoleButton:
        return cls(mode, entry.role_id, entry.label, entry.emoji, row)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ) -> RoleButton:
        return cls(
            PanelMode(match["mode"]),
            int(match["role_id"]),
            item.label or "role",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog(COG_NAME)
        # a throwaway tracker keeps a click working even with the cog
        # somehow unloaded; it just cannot reuse anything
        replies = cog.replies if isinstance(cog, Roles) else EphemeralReplies()
        await handle_click(interaction, self.mode, self.role_id, replies)


async def handle_click(
    interaction: discord.Interaction,
    mode: PanelMode,
    role_id: int,
    replies: EphemeralReplies,
) -> None:
    """Apply one button press to the clicker's roles."""
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        # panels are guild_only, so this is a shape that shouldn't happen
        await interaction.response.send_message(
            "Role buttons only work inside a server.", ephemeral=True
        )
        return

    # one reply per person per panel, so a run of clicks rewrites a single
    # message instead of stacking up a column of them
    key = (member.id, interaction.message.id if interaction.message else None)
    colour = colour_from_message(interaction.message)

    role = guild.get_role(role_id)
    if role is None:
        log.info("panel click for missing role %s in guild %s", role_id, guild.id)
        await replies.send(
            interaction,
            embed=_reply_embed(
                "That role doesn't exist any more. I'll tidy the panel up.", colour
            ),
            key=key,
        )
        return

    # re-checked on every click, not just at setup: role positions get
    # reorganised and the permission can be revoked long after the panel
    # was built
    rejection = _rejection_for(role)
    if rejection is not None:
        log.info(
            "refusing %s for %s in %s: %s",
            role.name,
            member,
            guild.name,
            rejection.value,
        )
        await replies.send(
            interaction,
            embed=_reply_embed(REJECTIONS[rejection].format(role=role.name), colour),
            key=key,
        )
        return

    held = {r.id for r in member.roles}
    # read from the message for every mode, not just the exclusive one: the
    # reply reports where the clicker now stands on the whole panel
    panel_roles = panel_roles_from_message(interaction.message)
    change = resolve_click(mode, role_id, held, panel_roles)
    if not change.changed:
        await replies.send(
            interaction,
            embed=_reply_embed(
                f"You already have {role.name}.\n{_standing(guild, held, panel_roles)}",
                colour,
            ),
            key=key,
        )
        return

    # the edit is a single request but the gateway can be slow, and a
    # deferred interaction is far better than a timed-out one
    await interaction.response.defer(ephemeral=True)

    # @everyone is implicit and Discord rejects it in the roles list
    target = final_roles(held, change) - {guild.default_role.id}
    try:
        await member.edit(
            roles=[discord.Object(id=i) for i in target],
            reason=f"role panel, clicked by {member} ({member.id})",
        )
    except discord.Forbidden:
        # the checks above passed, so the hierarchy moved under us between
        # the check and the write
        log.warning("forbidden assigning %s to %s", role.name, member.id)
        await replies.send(
            interaction,
            embed=_reply_embed(
                REJECTIONS[RoleRejection.OUTRANKED].format(role=role.name), colour
            ),
            key=key,
        )
        return
    except discord.HTTPException:
        log.exception("role edit failed for %s in guild %s", member.id, guild.id)
        await replies.send(
            interaction,
            embed=_reply_embed(
                "Discord wouldn't take that change just now. Try again in a moment.",
                colour,
            ),
            key=key,
        )
        return

    # role names rather than ids: reading these back is the main way a panel
    # gets debugged, and one id per role turns every line into a wall
    log.info(
        "%s (%s) in %s: +[%s] -[%s]",
        member,
        member.id,
        guild.name,
        _names(guild, change.add),
        _names(guild, change.remove),
    )
    await replies.send(
        interaction,
        embed=_reply_embed(
            f"{_describe(guild, change)}\n{_standing(guild, target, panel_roles)}",
            colour,
        ),
        key=key,
    )


def _reply_embed(text: str, colour: discord.Colour) -> discord.Embed:
    """A click confirmation, wearing the colour of the panel it came from."""
    return discord.Embed(description=text, colour=colour)


def _standing(
    guild: discord.Guild, held: frozenset[int] | set[int], panel_roles: frozenset[int]
) -> str:
    """Where the clicker now stands on this panel.

    The reply is rewritten in place on every click, so it reads as a live
    readout rather than a running commentary of one-off changes.
    """
    mine = _names(guild, frozenset(held) & panel_roles)
    return f"On this panel you have: {mine}." if mine else "You have none of these."


def _names(guild: discord.Guild, ids: frozenset[int]) -> str:
    found = [r.name for r in (guild.get_role(i) for i in ids) if r]
    return ", ".join(sorted(found))


def _describe(guild: discord.Guild, change: RoleChange) -> str:
    def names(ids) -> str:
        return _names(guild, ids)

    if change.add and change.remove:
        return f"Swapped {names(change.remove)} for {names(change.add)}."
    if change.add:
        return f"Given you {names(change.add)}."
    return f"Taken {names(change.remove)} away."


async def _reply(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
) -> None:
    """Answer an interaction whether or not it has already been deferred.

    The admin commands defer before touching Discord, so their replies
    have to go out as followups, while their early validation replies
    have not deferred yet.
    """
    kwargs = {
        "ephemeral": True,
        "allowed_mentions": discord.AllowedMentions.none(),
    }
    if embed is not None:
        kwargs["embed"] = embed
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


def render_embed(panel: Panel) -> discord.Embed:
    embed = discord.Embed(
        title=panel.title,
        description=panel.body or None,
        colour=_colour(panel.colour),
    )
    footer = MODE_BLURB[panel.mode]
    if not panel.entries:
        footer = f"no roles on this panel yet, {footer} once there are"
    embed.set_footer(text=footer)
    return embed


def build_view(panel: Panel) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for row_index, row in enumerate(pack_rows(panel.entries)):
        for entry in row:
            view.add_item(RoleButton.from_entry(entry, panel.mode, row_index))
    return view


@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
class Roles(commands.GroupCog, name=COG_NAME):
    """Admin surface. Discord itself gates this on Manage Roles."""

    def __init__(self, bot: commands.Bot, store: PanelStore):
        self.bot = bot
        self.store = store
        # shared by every panel click in this process, keyed per person
        # per panel inside
        self.replies = EphemeralReplies()
        super().__init__()

    # panels are edited in place, so every command that changes one ends
    # by rewriting its message

    async def _rewrite(self, panel: Panel) -> bool:
        """Push a panel's current state to its message. False if it's gone."""
        if panel.message_id is None:
            return False
        channel = self.bot.get_channel(panel.channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return False
        message = channel.get_partial_message(panel.message_id)
        try:
            await message.edit(embed=render_embed(panel), view=build_view(panel))
        except discord.NotFound:
            log.info("panel %s has lost its message", panel.name)
            await self.store.set_message_id(panel.guild_id, panel.name, None)
            return False
        return True

    async def _panel_or_complain(
        self, interaction: discord.Interaction, name: str
    ) -> Panel | None:
        panel = await self.store.get_panel(interaction.guild_id, name)
        if panel is None:
            await _reply(
                interaction,
                f"There's no panel called '{name}'. /roles list shows what there is.",
            )
        return panel

    async def panel_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        panels = await self.store.list_panels(interaction.guild_id)
        needle = current.lower()
        return [
            app_commands.Choice(name=p.name, value=p.name)
            for p in panels
            if needle in p.name.lower()
        ][:25]

    async def colour_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        # suggestions only: the field still takes a hex code typed straight in
        needle = current.lower().replace(" ", "_").replace("-", "_")
        return [
            app_commands.Choice(name=name.replace("_", " "), value=name)
            for name in NAMED_COLOURS
            if needle in name
        ][:25]

    @app_commands.command(description="Post a new empty role panel")
    @app_commands.describe(
        name="Short name you'll use to edit it later, e.g. pronouns",
        channel="Where to post it",
        mode="How the buttons relate to each other",
        title="Heading shown on the panel",
        body="Optional line of explanation under the heading",
        colour="A name like blurple, or a hex code like #ff8800",
    )
    @app_commands.autocomplete(colour=colour_autocomplete)
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        mode: PanelMode,
        title: str,
        body: str = "",
        colour: str | None = None,
    ) -> None:
        if not NAME_PATTERN.match(name):
            await _reply(
                interaction,
                "Panel names are lowercase letters, numbers and hyphens, up "
                "to 31 characters. Something like 'pronouns' or 'game-pings'.",
            )
            return
        if await self.store.get_panel(interaction.guild_id, name) is not None:
            await _reply(interaction, f"There's already a panel called '{name}'.")
            return
        value = None if colour is None else resolve_colour(colour)
        if colour is not None and value is None:
            await _reply(interaction, _BAD_COLOUR.format(given=colour))
            return

        await interaction.response.defer(ephemeral=True)

        panel = Panel(
            guild_id=interaction.guild_id,
            name=name,
            channel_id=channel.id,
            mode=mode,
            title=title,
            body=body,
            colour=value,
        )
        try:
            message = await channel.send(
                embed=render_embed(panel), view=build_view(panel)
            )
        except discord.Forbidden:
            await _reply(
                interaction,
                f"I can't post in {channel.mention}. I need View Channel, "
                "Send Messages and Embed Links there.",
            )
            return

        await self.store.save_panel(dataclasses.replace(panel, message_id=message.id))
        log.info("created panel %s in guild %s", name, interaction.guild_id)
        await _reply(
            interaction,
            f"Posted '{name}' in {channel.mention}. Add roles to it with "
            f"/roles add panel:{name}.",
        )

    @app_commands.command(description="Put a role on a panel")
    @app_commands.describe(
        panel="Which panel",
        role="The role to hand out",
        label="Button text, defaults to the role name",
        emoji="Optional emoji on the button",
    )
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def add(
        self,
        interaction: discord.Interaction,
        panel: str,
        role: discord.Role,
        label: str | None = None,
        emoji: str | None = None,
    ) -> None:
        existing = await self._panel_or_complain(interaction, panel)
        if existing is None:
            return

        rejection = _rejection_for(role)
        if rejection is not None:
            await _reply(interaction, REJECTIONS[rejection].format(role=role.name))
            return
        if role.id not in existing.role_ids and len(existing.entries) >= MAX_ENTRIES:
            await _reply(
                interaction,
                f"'{panel}' is full at {MAX_ENTRIES} buttons, which is "
                "Discord's ceiling for one message. Split it into a second "
                "panel.",
            )
            return

        await interaction.response.defer(ephemeral=True)

        updated = existing.with_entry(
            PanelEntry(
                position=len(existing.entries),
                role_id=role.id,
                label=(label or role.name)[:MAX_LABEL],
                emoji=emoji,
            )
        )
        try:
            posted = await self._rewrite(updated)
        except discord.HTTPException as exc:
            # almost always a malformed emoji, which Discord rejects at
            # edit time rather than telling us what it would accept
            log.warning("panel %s rejected by discord: %s", panel, exc.text)
            await _reply(
                interaction,
                f"Discord wouldn't accept that button: {exc.text}. If you "
                "passed an emoji, try a plain one like 🦊, or a custom one "
                "from this server.",
            )
            return

        await self.store.save_panel(updated)
        note = "" if posted else " The panel's message is missing, /roles repost it."
        await _reply(interaction, f"Added {role.mention} to '{panel}'.{note}")

    @app_commands.command(description="Take a role off a panel")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def remove(
        self, interaction: discord.Interaction, panel: str, role: discord.Role
    ) -> None:
        existing = await self._panel_or_complain(interaction, panel)
        if existing is None:
            return
        if role.id not in existing.role_ids:
            await _reply(interaction, f"{role.name} isn't on '{panel}'.")
            return

        await interaction.response.defer(ephemeral=True)
        updated = existing.without_role(role.id)
        await self._rewrite(updated)
        await self.store.save_panel(updated)
        # nobody loses the role itself, only the button that grants it
        await _reply(
            interaction,
            f"Took {role.name} off '{panel}'. Anyone who already has the "
            "role keeps it.",
        )

    @app_commands.command(description="Move a role's button along a panel")
    @app_commands.describe(position="0 is the first button")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def order(
        self,
        interaction: discord.Interaction,
        panel: str,
        role: discord.Role,
        position: int,
    ) -> None:
        existing = await self._panel_or_complain(interaction, panel)
        if existing is None:
            return
        if role.id not in existing.role_ids:
            await _reply(interaction, f"{role.name} isn't on '{panel}'.")
            return

        await interaction.response.defer(ephemeral=True)
        updated = existing.with_role_at(role.id, position)
        await self._rewrite(updated)
        await self.store.save_panel(updated)
        await _reply(interaction, f"Moved {role.name} on '{panel}'.")

    @app_commands.command(name="colour", description="Recolour a panel")
    @app_commands.describe(colour="A name like blurple, or a hex code like #ff8800")
    @app_commands.autocomplete(panel=panel_autocomplete, colour=colour_autocomplete)
    async def recolour(
        self, interaction: discord.Interaction, panel: str, colour: str
    ) -> None:
        existing = await self._panel_or_complain(interaction, panel)
        if existing is None:
            return
        value = resolve_colour(colour)
        if value is None:
            await _reply(interaction, _BAD_COLOUR.format(given=colour))
            return

        await interaction.response.defer(ephemeral=True)
        updated = dataclasses.replace(existing, colour=value)
        posted = await self._rewrite(updated)
        await self.store.save_panel(updated)
        note = "" if posted else " The panel's message is missing, /roles repost it."
        await _reply(interaction, f"'{panel}' is now #{value:06x}.{note}")

    @app_commands.command(name="list", description="Show this server's panels")
    async def list_panels(self, interaction: discord.Interaction) -> None:
        panels = await self.store.list_panels(interaction.guild_id)
        if not panels:
            await _reply(interaction, "No panels yet. /roles create makes one.")
            return

        embed = discord.Embed(title="Role panels", color=discord.Color.blurple())
        for p in panels:
            where = f"<#{p.channel_id}>"
            if p.message_id is None:
                where += " (message missing, needs a repost)"
            roles = ", ".join(f"<@&{e.role_id}>" for e in p.ordered()) or "empty"
            embed.add_field(
                name=f"{p.name} · {p.mode.value}",
                value=f"{where}\n{roles}",
                inline=False,
            )
        await _reply(interaction, embed=embed)

    @app_commands.command(description="Post a panel again, or move it")
    @app_commands.describe(channel="Somewhere new, or leave blank to stay put")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def repost(
        self,
        interaction: discord.Interaction,
        panel: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        existing = await self._panel_or_complain(interaction, panel)
        if existing is None:
            return

        target = channel or self.bot.get_channel(existing.channel_id)
        if not isinstance(target, discord.abc.Messageable):
            await _reply(
                interaction,
                "I can't see that panel's channel any more. Pass a channel "
                "to move it somewhere I can reach.",
            )
            return

        await interaction.response.defer(ephemeral=True)

        # the old message is left alone rather than deleted: it may be the
        # thing that is already gone, and deleting is not ours to guess at
        try:
            message = await target.send(
                embed=render_embed(existing), view=build_view(existing)
            )
        except discord.Forbidden:
            await _reply(interaction, f"I can't post in {target.mention}.")
            return
        except discord.HTTPException as exc:
            # a panel edited while its message was missing can hold a button
            # Discord will not render, and this is where that surfaces
            log.warning("could not repost panel %s: %s", panel, exc.text)
            await _reply(
                interaction,
                f"Discord wouldn't render '{panel}': {exc.text}. Check the "
                "emoji on its buttons with /roles list.",
            )
            return

        await self.store.save_panel(
            dataclasses.replace(existing, channel_id=target.id, message_id=message.id)
        )
        await _reply(
            interaction,
            f"Reposted '{panel}' in {target.mention}. If the old message is "
            "still around, delete it by hand.",
        )

    @app_commands.command(name="delete", description="Delete a panel entirely")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def delete_panel(self, interaction: discord.Interaction, panel: str) -> None:
        existing = await self._panel_or_complain(interaction, panel)
        if existing is None:
            return

        await interaction.response.defer(ephemeral=True)
        if existing.message_id is not None:
            channel = self.bot.get_channel(existing.channel_id)
            if isinstance(channel, discord.abc.Messageable):
                try:
                    await channel.get_partial_message(existing.message_id).delete()
                except discord.HTTPException:
                    log.info("could not delete message for panel %s", panel)

        await self.store.delete_panel(interaction.guild_id, panel)
        log.info("deleted panel %s in guild %s", panel, interaction.guild_id)
        await _reply(
            interaction, f"'{panel}' is gone. Nobody loses the roles it handed out."
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        for panel in await self.store.panels_with_role(role.guild.id, role.id):
            updated = panel.without_role(role.id)
            try:
                await self._rewrite(updated)
            except discord.HTTPException:
                # storage still gets the update, so a later repost is clean
                log.warning("could not rewrite panel %s", panel.name)
            await self.store.save_panel(updated)
            log.info("dropped deleted role %s from panel %s", role.id, panel.name)

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        panel = await self.store.panel_for_message(payload.message_id)
        if panel is not None:
            # the definition outlives the message so /roles repost can
            # rebuild it
            await self.store.set_message_id(panel.guild_id, panel.name, None)
            log.info("panel %s lost its message, kept the definition", panel.name)


async def setup(bot: commands.Bot) -> None:
    # one registration covers every panel ever posted, including those
    # from processes that no longer exist
    bot.add_dynamic_items(RoleButton)
    await bot.add_cog(Roles(bot, bot.db))
