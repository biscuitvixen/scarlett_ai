from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scarlett.timeparse import extract_times

LONDON = ZoneInfo("Europe/London")
CHICAGO = ZoneInfo("America/Chicago")

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


def test_relative_minutes():
    (m,) = extract_times("starting in 45 minutes", LONDON, NOW)
    assert int(m.when.timestamp()) == int(NOW.timestamp()) + 45 * 60


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


def test_imminent_time_stays_today():
    # said at 20:55 about 21:00 the same evening; dateparser compares bare
    # times against the base in UTC, which used to shift this to tomorrow
    # for any zone ahead of UTC (BST here)
    late = datetime(2026, 7, 11, 20, 55, tzinfo=LONDON)
    (m,) = extract_times("social will start at 21:00", LONDON, late)
    assert int(m.when.timestamp()) == unix(2026, 7, 11, 21, 0)


def test_relative_and_absolute_mixed():
    text = "starting in 45 minutes, so 14:45"
    matches = extract_times(text, LONDON, NOW)
    stamps = {int(m.when.timestamp()) for m in matches}
    assert stamps == {int(NOW.timestamp()) + 45 * 60}


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
