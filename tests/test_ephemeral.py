import asyncio

import discord
import pytest

from scarlett.ephemeral import EphemeralReplies, should_reuse

ALICE = ("alice", 1)
BOB = ("bob", 1)


@pytest.mark.parametrize(
    "age, expired, expected",
    [
        (None, False, False),  # nothing remembered yet
        (0.0, False, True),  # same instant
        (30.0, False, True),  # inside the burst
        (60.0, False, True),  # exactly on the boundary
        (60.1, False, False),  # quiet long enough to assume it was dismissed
        (1.0, True, False),  # token dead, the edit would fail
    ],
)
def test_reuse_decision(age, expired, expected):
    assert should_reuse(age=age, expired=expired, window=60.0) is expected, (
        f"age={age} expired={expired} decided wrongly"
    )


class FakeMessage:
    def __init__(self, content, fail=False):
        self.content = content
        self.fail = fail
        self.edits = 0

    async def edit(self, **payload):
        self.edits += 1
        if self.fail:
            raise discord.HTTPException(_Response(), "nope")
        self.__dict__.update(payload)


class _Response:
    status = 404
    reason = "Not Found"


class FakeResponse:
    def __init__(self):
        self.done = False
        self.defers = 0

    def is_done(self):
        return self.done

    async def defer(self, *, ephemeral=False):
        self.defers += 1
        self.done = True


class FakeFollowup:
    def __init__(self, interaction):
        self.interaction = interaction

    async def send(self, content=None, *, ephemeral=False, embed=None):
        message = FakeMessage(content, fail=self.interaction.edits_fail)
        message.embed = embed
        self.interaction.sent.append(message)
        return message


class FakeInteraction:
    """Enough of an Interaction for the tracker, with no gateway in sight."""

    def __init__(self, *, expired=False, edits_fail=False):
        self.response = FakeResponse()
        self.followup = FakeFollowup(self)
        self.expired = expired
        self.edits_fail = edits_fail
        self.sent = []

    def is_expired(self):
        return self.expired


def run(coro):
    return asyncio.run(coro)


def test_the_first_reply_is_a_new_message():
    clock = iter([0.0])
    replies = EphemeralReplies(clock=lambda: next(clock))
    it = FakeInteraction()

    run(replies.send(it, "hello", key=ALICE))

    assert len(it.sent) == 1, "the first reply should send a message"
    assert it.sent[0].content == "hello", "the message carried the wrong text"


def test_a_second_click_edits_the_first_message():
    times = iter([0.0, 5.0])
    replies = EphemeralReplies(clock=lambda: next(times))
    first, second = FakeInteraction(), FakeInteraction()

    run(replies.send(first, "one", key=ALICE))
    run(replies.send(second, "two", key=ALICE))

    assert second.sent == [], "the second click should not send a new message"
    assert first.sent[0].content == "two", "the first message should have been edited"


def test_the_second_click_is_acknowledged_silently():
    times = iter([0.0, 5.0])
    replies = EphemeralReplies(clock=lambda: next(times))
    first, second = FakeInteraction(), FakeInteraction()

    run(replies.send(first, "one", key=ALICE))
    run(replies.send(second, "two", key=ALICE))

    assert second.response.defers == 1, (
        "a reused reply still has to acknowledge its interaction"
    )


def test_a_quiet_gap_starts_a_fresh_message():
    times = iter([0.0, 500.0])
    replies = EphemeralReplies(window=60.0, clock=lambda: next(times))
    first, second = FakeInteraction(), FakeInteraction()

    run(replies.send(first, "one", key=ALICE))
    run(replies.send(second, "two", key=ALICE))

    assert len(second.sent) == 1, "a click after the window should send a new message"
    assert first.sent[0].content == "one", "the old message should be left alone"


def test_an_expired_token_starts_a_fresh_message():
    times = iter([0.0, 5.0])
    replies = EphemeralReplies(clock=lambda: next(times))
    first = FakeInteraction(expired=True)
    second = FakeInteraction()

    run(replies.send(first, "one", key=ALICE))
    run(replies.send(second, "two", key=ALICE))

    assert len(second.sent) == 1, "a dead token should not be edited"


def test_a_refused_edit_falls_back_to_a_new_message():
    # what a dismissed message looks like from here: the edit is refused
    # and the person is owed a reply they can actually see
    times = iter([0.0, 5.0])
    replies = EphemeralReplies(clock=lambda: next(times))
    first = FakeInteraction(edits_fail=True)
    second = FakeInteraction()

    run(replies.send(first, "one", key=ALICE))
    run(replies.send(second, "two", key=ALICE))

    assert first.sent[0].edits == 1, "the edit should have been attempted"
    assert len(second.sent) == 1, "a refused edit should fall back to a new message"


def test_people_do_not_share_a_reply():
    times = iter([0.0, 1.0, 2.0])
    replies = EphemeralReplies(clock=lambda: next(times))
    alice, bob = FakeInteraction(), FakeInteraction()

    run(replies.send(alice, "alice one", key=ALICE))
    run(replies.send(bob, "bob one", key=BOB))

    assert len(bob.sent) == 1, "a different person should get their own message"
    assert alice.sent[0].content == "alice one", "one person's reply was overwritten"


def test_reuse_keeps_extending_the_window():
    # the window is measured from the last reply, so a steady stream of
    # clicks keeps rewriting one message however long it goes on
    times = iter([0.0, 50.0, 100.0, 150.0])
    replies = EphemeralReplies(window=60.0, clock=lambda: next(times))
    first = FakeInteraction()

    run(replies.send(first, "one", key=ALICE))
    for text in ("two", "three", "four"):
        run(replies.send(FakeInteraction(), text, key=ALICE))

    assert first.sent[0].content == "four", "a steady stream should keep one message"


def test_expired_entries_are_dropped():
    times = iter([0.0, 500.0])
    replies = EphemeralReplies(window=60.0, clock=lambda: next(times))

    run(replies.send(FakeInteraction(), "one", key=ALICE))
    run(replies.send(FakeInteraction(), "two", key=BOB))

    assert ALICE not in replies.replies, "a stale entry should have been pruned"
    assert BOB in replies.replies, "the fresh entry should have been kept"


def test_forgetting_a_key_starts_fresh():
    times = iter([0.0, 5.0])
    replies = EphemeralReplies(clock=lambda: next(times))
    first, second = FakeInteraction(), FakeInteraction()

    run(replies.send(first, "one", key=ALICE))
    replies.forget(ALICE)
    run(replies.send(second, "two", key=ALICE))

    assert len(second.sent) == 1, "a forgotten key should send a new message"


def test_an_embed_reply_is_reused_like_any_other():
    times = iter([0.0, 5.0])
    replies = EphemeralReplies(clock=lambda: next(times))
    first, second = FakeInteraction(), FakeInteraction()
    one = discord.Embed(description="one", colour=discord.Colour(0xFF8800))
    two = discord.Embed(description="two", colour=discord.Colour(0xFF8800))

    run(replies.send(first, embed=one, key=ALICE))
    run(replies.send(second, embed=two, key=ALICE))

    assert second.sent == [], "an embed reply should reuse the message too"
    assert first.sent[0].embed is two, "the embed should have been replaced"


def test_only_what_was_given_is_sent_on():
    # passing content=None through to an edit would blank the text half of
    # a message that is meant to keep it
    clock = iter([0.0])
    replies = EphemeralReplies(clock=lambda: next(clock))
    it = FakeInteraction()

    run(replies.send(it, embed=discord.Embed(description="hi"), key=ALICE))

    assert it.sent[0].content is None, "no content should have been sent"
    assert it.sent[0].embed is not None, "the embed should have been sent"
