import asyncio
from unittest.mock import AsyncMock, Mock

from scarlett.cogs.timestamps import Timestamps


def make_cog(tz_name=None):
    bot = Mock()
    bot.db = Mock()
    bot.db.get_timezone = AsyncMock(return_value=tz_name)
    return Timestamps(bot)


def make_message(content, author_id=1, is_bot=False):
    message = Mock()
    message.content = content
    message.author.id = author_id
    message.author.bot = is_bot
    message.reply = AsyncMock()
    return message


def run(coro):
    return asyncio.run(coro)


def reply_text(message):
    return message.reply.call_args.args[0]


def test_prompt_quotes_the_matched_phrase():
    # the message that started all this: a bare "noon" with no tz on file
    cog = make_cog(tz_name=None)
    msg = make_message("I had shawarma for breakfast at noon, walked back")
    run(cog.on_message(msg))
    msg.reply.assert_called_once()
    text = reply_text(msg)
    assert '"noon"' in text
    assert "/tz" in text


def test_prompt_preserves_original_casing():
    cog = make_cog(tz_name=None)
    msg = make_message("lunch at NOON tomorrow")
    run(cog.on_message(msg))
    assert '"NOON"' in reply_text(msg)


def test_prompt_quotes_a_clock_time():
    cog = make_cog(tz_name=None)
    msg = make_message("dinner at 7:30 pm sound good?")
    run(cog.on_message(msg))
    assert '"7:30 pm"' in reply_text(msg)


def test_prompt_is_rate_limited_per_user():
    cog = make_cog(tz_name=None)
    first = make_message("noon", author_id=5)
    second = make_message("midnight", author_id=5)
    run(cog.on_message(first))
    run(cog.on_message(second))
    first.reply.assert_called_once()
    # inside PROMPT_COOLDOWN, the second mention stays quiet
    second.reply.assert_not_called()


def test_bot_messages_are_ignored():
    cog = make_cog(tz_name=None)
    msg = make_message("meet at 7pm", is_bot=True)
    run(cog.on_message(msg))
    msg.reply.assert_not_called()
    cog.bot.db.get_timezone.assert_not_called()


def test_message_without_a_time_is_ignored():
    cog = make_cog(tz_name=None)
    msg = make_message("see you friday")
    run(cog.on_message(msg))
    msg.reply.assert_not_called()
    cog.bot.db.get_timezone.assert_not_called()


def test_preformatted_timestamp_is_ignored():
    cog = make_cog(tz_name=None)
    msg = make_message("meet at <t:1751652000:F> please")
    run(cog.on_message(msg))
    msg.reply.assert_not_called()


def test_known_timezone_replies_with_conversion():
    cog = make_cog(tz_name="Europe/London")
    msg = make_message("dinner at 7pm tomorrow")
    run(cog.on_message(msg))
    msg.reply.assert_called_once()
    text = reply_text(msg)
    assert "<t:" in text
    # the reply quotes the matched phrase, which dateparser returns with its
    # surrounding words ("at 7pm tomorrow"), not just the clock time
    assert '"' in text and "7pm" in text


def test_gate_hit_with_nothing_to_convert_stays_quiet():
    # "in 5 minutes" trips the regex gate but is under the minimum lead, so
    # extract_times finds nothing and a tz-known user gets no noisy reply
    cog = make_cog(tz_name="Europe/London")
    msg = make_message("leaving in 5 minutes")
    run(cog.on_message(msg))
    msg.reply.assert_not_called()
