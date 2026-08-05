"""Self-assignable role panels: the parts that are not Discord's problem.

A panel is a message carrying one button per role. Clicking a button
adds or removes that role, so members pick their own pronouns, game
pings or colours without anyone with Manage Roles being awake.

Membership is never stored here. Discord already knows who holds which
role and is the only authority on it; a panel is a description of which
buttons exist and what mode they behave in. Panel definitions are held
behind the PanelStore protocol rather than a concrete database, so the
same panel logic can sit on top of any bot's storage.

Every button carries its mode and role id in its own custom_id, so a
click resolves from the message alone. The store is a durable backup
and the editing index, not a lookup on the click path.

No discord imports: the whole module is exercisable without a gateway
connection, and portable to another bot as-is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

# Discord allows 5 action rows per message, 5 buttons each
MAX_ROW_WIDTH = 5
MAX_ROWS = 5
MAX_ENTRIES = MAX_ROW_WIDTH * MAX_ROWS

# button labels are capped by Discord at 80 characters
MAX_LABEL = 80

# leads every custom_id this module owns, so a panel button is
# distinguishable from any other component the bot might grow later
CUSTOM_ID_PREFIX = "rr"


class PanelMode(StrEnum):
    """How the buttons on one panel relate to each other."""

    # each role is independent, click to toggle
    MULTI = "multi"
    # at most one role from the panel at a time, clicking one drops the rest
    SINGLE = "single"
    # click to gain the role, never to lose it. rules agreement, verification
    STICKY = "sticky"


class RoleRejection(StrEnum):
    """Why a role cannot be put on a panel, or clicked once it is there."""

    NO_MANAGE_ROLES = "no_manage_roles"
    OUTRANKED = "outranked"
    IS_DEFAULT = "is_default"
    IS_MANAGED = "is_managed"


@dataclass(frozen=True, order=True)
class PanelEntry:
    """One button. `position` orders the buttons and packs them into rows."""

    position: int
    role_id: int
    label: str
    emoji: str | None = None


@dataclass(frozen=True)
class Panel:
    guild_id: int
    name: str
    channel_id: int
    mode: PanelMode
    title: str
    body: str = ""
    # None while the panel has never been posted, or once its message has
    # been deleted and the definition is waiting to be reposted
    message_id: int | None = None
    entries: tuple[PanelEntry, ...] = ()
    # 0xRRGGBB for the panel's embed, None to leave it to the caller's
    # default. plain int rather than a Discord colour so this module keeps
    # to itself
    colour: int | None = None

    @property
    def role_ids(self) -> frozenset[int]:
        return frozenset(e.role_id for e in self.entries)

    def ordered(self) -> tuple[PanelEntry, ...]:
        return tuple(sorted(self.entries))

    def with_entry(self, entry: PanelEntry) -> Panel:
        """Return a copy with `entry` added, or replacing the same role."""
        kept = [e for e in self.ordered() if e.role_id != entry.role_id]
        return self._replace_entries([*kept, entry])

    def without_role(self, role_id: int) -> Panel:
        return self._replace_entries(
            [e for e in self.ordered() if e.role_id != role_id]
        )

    def with_role_at(self, role_id: int, position: int) -> Panel:
        """Move one role to `position`, shuffling the others around it."""
        moving = next((e for e in self.entries if e.role_id == role_id), None)
        if moving is None:
            return self
        rest = [e for e in self.ordered() if e.role_id != role_id]
        index = max(0, min(position, len(rest)))
        rest.insert(index, moving)
        return self._replace_entries(rest)

    def _replace_entries(self, entries: Iterable[PanelEntry]) -> Panel:
        # the iterable's own order is the new button order, and positions
        # are renumbered from scratch onto it so they stay dense. callers
        # that mean "keep the existing order" pass ordered() in
        renumbered = tuple(
            PanelEntry(i, e.role_id, e.label, e.emoji) for i, e in enumerate(entries)
        )
        # replace() rather than rebuilding field by field, so a field added
        # to the panel later cannot be silently dropped here
        return replace(self, entries=renumbered)


@dataclass(frozen=True)
class RoleChange:
    """The difference between the roles someone holds and should hold."""

    add: frozenset[int] = frozenset()
    remove: frozenset[int] = frozenset()

    @property
    def changed(self) -> bool:
        return bool(self.add or self.remove)


def encode_custom_id(mode: PanelMode, role_id: int) -> str:
    return f"{CUSTOM_ID_PREFIX}:{mode.value}:{role_id}"


def decode_custom_id(raw: str) -> tuple[PanelMode, int] | None:
    """Parse a button id back into its mode and role, None if it isn't ours.

    Anything unparseable is a None rather than an exception: the same
    message can carry components this module did not put there, and a
    stray one should be ignored, not crash a click handler.
    """
    parts = raw.split(":")
    if len(parts) != 3 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    try:
        mode = PanelMode(parts[1])
        role_id = int(parts[2])
    except ValueError:
        return None
    return mode, role_id


def resolve_click(
    mode: PanelMode,
    clicked: int,
    held: Iterable[int],
    panel_roles: Iterable[int],
) -> RoleChange:
    """Work out what a click on `clicked` should do to someone's roles.

    `panel_roles` matters only in SINGLE mode, where the roles that lose
    out are the other roles on the same panel. Roles held from elsewhere
    are never touched.
    """
    held = frozenset(held)
    if mode is PanelMode.STICKY:
        # deliberately one-way: a rules-agreement button that could be
        # un-clicked is not an agreement
        return RoleChange() if clicked in held else RoleChange(add={clicked})

    if clicked in held:
        # in SINGLE mode too, so a panel is never a trap you can't leave
        return RoleChange(remove={clicked})

    if mode is PanelMode.SINGLE:
        # a member can hold several panel roles already if they were
        # assigned by hand before the panel existed, so this strips every
        # sibling rather than assuming there is at most one
        siblings = (frozenset(panel_roles) & held) - {clicked}
        return RoleChange(add={clicked}, remove=siblings)

    return RoleChange(add={clicked})


def final_roles(held: Iterable[int], change: RoleChange) -> frozenset[int]:
    """The complete role set to write back.

    Applied in one request rather than an add followed by a remove, so a
    SINGLE swap has no window where the member holds both roles or
    neither.
    """
    return (frozenset(held) | change.add) - change.remove


def check_assignable(
    *,
    has_manage_roles: bool,
    bot_outranks: bool,
    is_default: bool,
    is_managed: bool,
) -> RoleRejection | None:
    """Whether the bot can hand out this role, None if it can.

    Callers pass plain facts rather than role objects. `bot_outranks` in
    particular is the caller's job because Discord ranks equal-position
    roles by id, which a bare position comparison gets wrong.
    """
    if is_default:
        return RoleRejection.IS_DEFAULT
    if is_managed:
        return RoleRejection.IS_MANAGED
    if not has_manage_roles:
        return RoleRejection.NO_MANAGE_ROLES
    if not bot_outranks:
        return RoleRejection.OUTRANKED
    return None


MAX_COLOUR = 0xFFFFFF

# #rgb, #rrggbb, and the 0x forms of both, with the hash and prefix optional
_HEX_COLOUR = re.compile(r"^(?:0x)?#?([0-9a-f]{3}|[0-9a-f]{6})$", re.I)


def parse_hex_colour(raw: str) -> int | None:
    """Read a hex colour, None if the text is not one.

    Shorthand expands the way CSS does, so f80 and ff8800 mean the same
    thing. Named colours are the caller's business, since their values
    belong to whatever is doing the rendering.
    """
    match = _HEX_COLOUR.match(raw.strip())
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(d * 2 for d in digits)
    return int(digits, 16)


def pack_rows(entries: Sequence[PanelEntry]) -> list[list[PanelEntry]]:
    """Split entries into Discord's action rows, in position order."""
    if len(entries) > MAX_ENTRIES:
        raise ValueError(
            f"a panel holds at most {MAX_ENTRIES} buttons, got {len(entries)}"
        )
    ordered = sorted(entries)
    return [
        ordered[i : i + MAX_ROW_WIDTH] for i in range(0, len(ordered), MAX_ROW_WIDTH)
    ]


class PanelStore(Protocol):
    """Durable panel definitions, backed by whatever the host bot uses.

    Deliberately narrow: panels in, panels out, no notion of members or
    role membership. Nothing on the click path calls it except the
    SINGLE-mode fallback.
    """

    async def get_panel(self, guild_id: int, name: str) -> Panel | None: ...

    async def list_panels(self, guild_id: int) -> list[Panel]: ...

    async def save_panel(self, panel: Panel) -> None: ...

    async def delete_panel(self, guild_id: int, name: str) -> None: ...

    async def set_message_id(
        self, guild_id: int, name: str, message_id: int | None
    ) -> None: ...

    async def panel_for_message(self, message_id: int) -> Panel | None: ...

    async def panels_with_role(self, guild_id: int, role_id: int) -> list[Panel]: ...
