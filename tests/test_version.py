import pytest

from scarlett.version import describe, short_sha


@pytest.mark.parametrize(
    "sha, expected",
    [
        ("1f65e17abcdef", "1f65e17"),
        ("1f65e17", "1f65e17"),
        ("  1f65e17  ", "1f65e17"),
        ("", None),
        (None, None),
    ],
)
def test_a_commit_is_trimmed_to_something_readable(sha, expected):
    assert short_sha(sha) == expected, f"{sha!r} trimmed wrongly"


def test_the_commit_is_named_when_there_is_one():
    assert describe("0.3.0", "1f65e17abc") == "0.3.0 (1f65e17)", "wrong description"


def test_the_version_stands_alone_when_the_commit_is_unknown():
    # running from a checkout, where nothing bakes the commit in
    assert describe("0.3.0", "") == "0.3.0", "an absent commit should not show"
    assert describe("0.3.0") == "0.3.0", "an absent commit should not show"


def test_the_version_command_is_gated_to_managers():
    # which build is running is an operator's question, and the gate is the
    # kind of thing that breaks without anything failing
    import asyncio

    import discord
    from discord.ext import commands

    from scarlett.cogs.general import General

    async def main():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        await bot.add_cog(General(bot))
        return next(c for c in bot.tree.get_commands() if c.name == "version")

    command = asyncio.run(main())
    assert command.guild_only, "asking which build is running is a server question"
    assert command.default_permissions == discord.Permissions(manage_guild=True), (
        "/version should default to Manage Server only"
    )
