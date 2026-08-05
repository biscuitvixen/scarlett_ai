"""One ephemeral reply per person, rewritten rather than repeated.

An ephemeral message has no lifetime of its own: it sits in the
recipient's client until they dismiss it or reload, and nobody else ever
sees it. A handler that answers every click with a fresh one therefore
leaves a stack of them behind, which is noise for anyone using a panel
properly rather than once.

Instead the first reply in a burst is sent and remembered, and later
replies edit it in place. Two Discord behaviours make that work:
deferring a component interaction acknowledges it without showing or
creating anything, leaving the reply free to be an edit; and a followup
message stays editable for as long as its interaction token lives, which
is fifteen minutes.

Past that window, or if the edit is refused, a fresh message is sent. A
quiet gap is treated the same way, on the assumption that a message
nobody has seen recently has probably been dismissed. Discord gives no
signal when that happens, so the gap is the only proxy available.

Unlike the panel logic this is Discord-specific by nature, since it is
about interaction tokens and ephemeral messages. It is reusable across
cogs and bots, but not across chat platforms.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass

import discord

log = logging.getLogger(__name__)

# how long after the last reply a click still counts as the same burst.
# past it the old message is assumed dismissed and a new one is sent
DEFAULT_REUSE_WINDOW = 60.0


def should_reuse(*, age: float | None, expired: bool, window: float) -> bool:
    """Whether the remembered reply can be edited instead of replaced.

    `age` is seconds since that reply was last written, or None when
    there is nothing remembered. `expired` reports the interaction token
    being dead, which would make the edit fail.
    """
    if age is None or expired:
        return False
    return age <= window


@dataclass
class _Reply:
    message: discord.WebhookMessage
    interaction: discord.Interaction
    at: float


class EphemeralReplies:
    """Remembers one ephemeral reply per key and rewrites it in place.

    The key is whatever scope should share a message, which for a role
    panel is one person on one panel. Callers hand over the interaction
    and the text; acknowledging, editing and falling back are all handled
    here.

    State is in memory and per process, so a restart simply means the
    next reply is a fresh message.
    """

    def __init__(
        self,
        *,
        window: float = DEFAULT_REUSE_WINDOW,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.window = window
        self.clock = clock
        self.replies: dict[Hashable, _Reply] = {}

    async def send(
        self,
        interaction: discord.Interaction,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        key: Hashable,
    ) -> None:
        # only what the caller supplied is passed on, so an edit leaves the
        # other half of the message as it was rather than blanking it
        payload: dict[str, object] = {}
        if content is not None:
            payload["content"] = content
        if embed is not None:
            payload["embed"] = embed

        now = self.clock()
        previous = self.replies.get(key)

        # acknowledge first. on a component interaction this defers as a
        # message update, which shows nothing and creates no message, so
        # the reply is free to be an edit of an older one
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        if previous is not None and should_reuse(
            age=now - previous.at,
            expired=previous.interaction.is_expired(),
            window=self.window,
        ):
            try:
                await previous.message.edit(**payload)
            except discord.HTTPException:
                # dismissed, deleted, or the token died between the check
                # and the edit. a fresh message is the answer either way
                log.debug("could not reuse the ephemeral for %r", key)
            else:
                previous.at = now
                return

        message = await interaction.followup.send(ephemeral=True, **payload)
        self.replies[key] = _Reply(message=message, interaction=interaction, at=now)
        self._prune(now)

    def forget(self, key: Hashable) -> None:
        """Drop a remembered reply, so the next one starts fresh."""
        self.replies.pop(key, None)

    def _prune(self, now: float) -> None:
        # an entry is only useful while it could still be reused, so the
        # map never grows past the people currently clicking
        stale = [
            key
            for key, reply in self.replies.items()
            if now - reply.at > self.window or reply.interaction.is_expired()
        ]
        for key in stale:
            del self.replies[key]
