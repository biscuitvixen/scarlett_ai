from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scarlett.timeparse import explicit_zone, extract_times

LONDON = ZoneInfo("Europe/London")
CHICAGO = ZoneInfo("America/Chicago")
PARIS = ZoneInfo("Europe/Paris")

# a Wednesday afternoon, BST
NOW = datetime(2026, 7, 1, 14, 0, tzinfo=LONDON)


def unix(*args, tz=LONDON):
    return int(datetime(*args, tzinfo=tz).timestamp())


def test_simple_pm():
    (m,) = extract_times("dinner at 7pm", LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 1, 19, 0)


def test_weekday_with_time():
    (m,) = extract_times("movie night friday at 7pm?", LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 3, 19, 0)


def test_24h_tomorrow():
    (m,) = extract_times("raid at 19:30 tomorrow", LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 2, 19, 30)


@pytest.mark.parametrize(
    "text",
    [
        "19:00",
        "19:00?",
        "19:00!",
        "19:00?!",
        "19:00 :P",
        "7pm",
        "7pm?",
        "7:00pm!",
    ],
)
def test_bare_time_alone_in_message(text):
    # a message that is nothing but the time, which is how people actually
    # answer "what time?" in chat
    (m,) = extract_times(text, LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 1, 19, 0)


def test_relative_hours():
    (m,) = extract_times("starting in 3 hours", LONDON, NOW)
    assert int(m.when.timestamp()) == int(NOW.timestamp()) + 3 * 3600


def test_relative_minutes_too_soon():
    # under the minimum lead, everyone can count to 45
    assert extract_times("starting in 45 minutes", LONDON, NOW) == []


def test_time_ninety_minutes_out_converts():
    # the evening-planning case: someone says 21:00 at 19:30 and the
    # timezones in the room are still an hour apart
    evening = datetime(2026, 7, 1, 19, 30, tzinfo=LONDON)
    (m,) = extract_times("21:00?", LONDON, evening)
    assert int(m.when.timestamp()) == unix(2026, 7, 1, 21, 0)


def test_compact_24h_with_at():
    (m,) = extract_times("movie night friday at 1900?", LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 3, 19, 0)


def test_compact_24h_leading_zero():
    (m,) = extract_times("briefing at 0730 tomorrow", LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 2, 7, 30)


def test_compact_24h_hrs_suffix():
    (m,) = extract_times("kickoff 1900hrs saturday", LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 4, 19, 0)


def test_noon_saturday():
    (m,) = extract_times("brunch at noon on saturday", LONDON, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 4, 12, 0)


def test_future_preference():
    # 3pm already passed at 5pm, should roll to tomorrow
    late = datetime(2026, 7, 1, 17, 0, tzinfo=LONDON)
    (m,) = extract_times("lets do 3pm", LONDON, late)
    assert int(m.when.timestamp()) == unix(2026, 7, 2, 15, 0)


def test_same_day_time_stays_today():
    # dateparser compares bare times against the base in UTC, which used to
    # shift anything within the utc offset to tomorrow. Auckland's +12 makes
    # that window huge, so this 7h-out mention would have landed on Sunday
    auckland = ZoneInfo("Pacific/Auckland")
    early = datetime(2026, 7, 11, 14, 0, tzinfo=auckland)
    (m,) = extract_times("social will start at 21:00", auckland, early)
    assert int(m.when.timestamp()) == unix(2026, 7, 11, 21, 0, tz=auckland)


def test_imminent_time_skipped():
    # 5 minutes out is below the minimum lead, stay quiet
    late = datetime(2026, 7, 11, 20, 55, tzinfo=LONDON)
    assert extract_times("social will start at 21:00", LONDON, late) == []


def test_zero_min_lead_converts_an_imminent_time():
    # what /time passes: asked outright, so the quiet-hours rule is off
    late = datetime(2026, 7, 11, 20, 55, tzinfo=LONDON)
    (m,) = extract_times(
        "21:00", LONDON, late, min_lead=timedelta(0)
    )
    assert int(m.when.timestamp()) == unix(2026, 7, 11, 21, 0)


def test_zero_min_lead_still_prefers_the_future():
    # 5 minutes past, so it belongs to tomorrow, not five minutes ago
    late = datetime(2026, 7, 11, 21, 5, tzinfo=LONDON)
    (m,) = extract_times("21:00", LONDON, late, min_lead=timedelta(0))
    assert int(m.when.timestamp()) == unix(2026, 7, 12, 21, 0)


def test_max_matches_override():
    text = "either 6pm, 7pm, 8pm or 9pm"
    assert len(extract_times(text, LONDON, NOW)) == 3
    assert len(extract_times(text, LONDON, NOW, max_matches=10)) == 4


def test_relative_and_absolute_mixed():
    text = "starting in 3 hours, so 17:00"
    matches = extract_times(text, LONDON, NOW)
    stamps = {int(m.when.timestamp()) for m in matches}
    assert stamps == {int(NOW.timestamp()) + 3 * 3600}


def test_timezone_changes_result():
    # same wall clock base in each zone, same phrase, 6h apart in July
    chi_now = datetime(2026, 7, 1, 14, 0, tzinfo=CHICAGO)
    (ldn,) = extract_times("call at 9am", LONDON, NOW)
    (chi,) = extract_times("call at 9am", CHICAGO, chi_now)
    diff = int(chi.when.timestamp()) - int(ldn.when.timestamp())
    assert diff == 6 * 3600


def test_dst_boundary():
    # said during BST about a date after the clocks go back
    before = datetime(2026, 10, 20, 12, 0, tzinfo=LONDON)
    (m,) = extract_times("party on november 1st at 7pm", LONDON, before)
    assert m.when.utcoffset().total_seconds() == 0


def test_multiple_capped_and_deduped():
    text = "either 6pm, 7pm, 8pm or 9pm, maybe 6pm again"
    matches = extract_times(text, LONDON, NOW)
    assert len(matches) == 3
    stamps = [int(m.when.timestamp()) for m in matches]
    assert len(set(stamps)) == 3


def test_stated_zone_without_a_registered_one():
    # nobody knows where the author is, but the message says so itself
    (m,) = extract_times("22:00 CET works for me", None, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 1, 22, 0, tz=PARIS)


def test_no_zone_anywhere_stays_quiet():
    assert extract_times("22:00 works for me", None, NOW) == []


def test_stated_zone_is_read_as_wall_clock():
    # July, so Paris is on CEST. Someone typing CET means the clock on their
    # wall, not a literal UTC+1, which would land this an hour early
    (m,) = extract_times("22:00 CET", None, NOW)
    assert m.when.utcoffset() == timedelta(hours=2)


def test_stated_zone_beats_the_registered_one():
    # author registered as Chicago, but they said CET
    (m,) = extract_times("22:00 CET", CHICAGO, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 1, 22, 0, tz=PARIS)


def test_stated_zone_covers_the_bare_times_beside_it():
    text = "22:00 CET is standard, but 21:00 was better for a few"
    stamps = {int(m.when.timestamp()) for m in extract_times(text, None, NOW)}
    assert stamps == {
        unix(2026, 7, 1, 22, 0, tz=PARIS),
        unix(2026, 7, 1, 21, 0, tz=PARIS),
    }


def test_stated_zone_is_quoted_back_in_the_phrase():
    (m,) = extract_times("22:00 CET works for me", None, NOW)
    assert m.phrase == "22:00 CET"
    # already in the phrase, so no separate label to tack on
    assert m.zone is None


def test_borrowed_zone_is_labelled_separately():
    text = "22:00 CET is standard, but 21:00 was better for a few"
    said, borrowed = extract_times(text, None, NOW)
    assert (said.phrase, said.zone) == ("22:00 CET", None)
    # 21:00 never named a zone, it inherited one. Say so
    assert (borrowed.phrase, borrowed.zone) == ("21:00", "CET")


def test_bracketed_zone_keeps_its_bracket():
    (m,) = extract_times("22:00 (CET) works", None, NOW)
    assert m.phrase == "22:00 (CET)"


def test_unplaceable_phrase_still_names_the_zone():
    # blanking the zone leaves a gap that dateparser closes up, so this
    # phrase cannot be found in the text again. It must not lose the zone
    (m,) = extract_times("raid at 19:00 UTC+2 tomorrow", None, NOW)
    assert m.zone == "UTC+2"
    assert int(m.when.timestamp()) == unix(2026, 7, 2, 17, 0, tz=ZoneInfo("UTC"))


def test_zone_before_the_time_is_quoted_too():
    (m,) = extract_times("CET 22:00 then", None, NOW)
    assert m.phrase == "CET 22:00"


def test_no_zone_label_when_none_was_stated():
    (m,) = extract_times("21:00 works", LONDON, NOW)
    assert m.zone is None


def test_numeric_offset_zone():
    (m,) = extract_times("raid at 19:00 UTC+2", None, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 1, 17, 0, tz=ZoneInfo("UTC"))


def test_utc_is_literal():
    (m,) = extract_times("19:00 UTC", None, NOW)
    assert int(m.when.timestamp()) == unix(2026, 7, 1, 19, 0, tz=ZoneInfo("UTC"))


@pytest.mark.parametrize(
    "text,label,expected",
    [
        ("22:00 CET", "CET", "Europe/Paris"),
        ("22:00 (CET)", "CET", "Europe/Paris"),
        ("8pm est", "est", "America/New_York"),
        ("the 19:00 PT stream", "PT", "America/Los_Angeles"),
        ("19:00 UTC", "UTC", "UTC"),
    ],
)
def test_explicit_zone_found(text, label, expected):
    stated = explicit_zone(text)
    assert stated.tz == ZoneInfo(expected)
    # the label is quoted back at the author, so it is what they typed
    assert stated.label == label


@pytest.mark.parametrize(
    "text",
    [
        "22:00 tomorrow",
        # French "and", which is why lowercase two letter names are ignored
        "on se voit a 19:00 et 20:00",
        # a zone far from any time is talking about something else
        "19:00 works, and my CET train was late",
        # not a zone we can pin down, India, Israel and Ireland all use IST
        "19:00 IST",
        # TIME_OF_DAY needs a non-word character after the time, so an
        # unspaced zone is never seen at all. Documenting, not endorsing
        "22:00CET",
    ],
)
def test_explicit_zone_not_found(text):
    assert explicit_zone(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "see you friday",
        "that costs $7.30",
        "we won 19-30",
        "may I ask something",
        "i have 7 apples",
        "back in 1900 things were different",
        "the code is 1730",
        "already formatted <t:1751652000:F> here",
    ],
)
def test_no_match(text):
    assert extract_times(text, LONDON, NOW) == []
