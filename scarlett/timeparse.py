"""Finds concrete times in chat messages.

Deterministic only. A cheap regex gate decides whether a message contains
an explicit time of day at all, then dateparser resolves the phrases in
the author's timezone. Bare dates ("friday") are ignored on purpose: a
timestamp without an hour does not help anyone coordinate, and requiring
a clock time kills most false positives (prices, scores, "may", "sat").
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import NamedTuple
from zoneinfo import ZoneInfo

from dateparser.search import search_dates


class TimeMatch(NamedTuple):
    phrase: str
    when: datetime  # timezone aware


TIME_OF_DAY = re.compile(
    r"""
      \b\d{1,2}(?::[0-5]\d)?\s*(?:am|pm)\b        # 7pm, 7:30 pm
    | \b(?:[01]?\d|2[0-3]):[0-5]\d\b              # 19:30
    | \bat\s+(?:[01]\d|2[0-3])[0-5]\d\b           # at 1900
    | \b(?:[01]\d|2[0-3])[0-5]\d\s*(?:hrs?|hours)\b   # 1900hrs
    | \b(?:noon|midday|midnight)\b
    | \bin\s+\d+\s*(?:minutes?|mins?|hours?|hrs?)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Compact 24h time ("1900") is only trusted with context ("at 1900",
# "1900hrs"), a bare 4-digit number is usually a year or just a number.
# dateparser reads "1900" as a year too, so rewrite to 19:00 before parsing.
COMPACT_24H_AT = re.compile(r"\b(at\s+)([01]\d|2[0-3])([0-5]\d)\b", re.IGNORECASE)
COMPACT_24H_HRS = re.compile(
    r"\b([01]\d|2[0-3])([0-5]\d)\s*(?:hrs?|hours)\b", re.IGNORECASE
)

# "in 45 minutes" is just now + delta, no parser needed. Handled here and
# blanked out of the text because dateparser's relative and absolute parsers
# want RELATIVE_BASE in different timezones (see extract_times), so no single
# call gets both right.
RELATIVE_IN = re.compile(
    r"\bin\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", re.IGNORECASE
)

# Timezones people actually type next to a time in chat, mapped to an IANA
# zone rather than the offset the abbreviation literally names. Someone
# writing "22:00 CET" in July means 22:00 on a Paris wall clock, even though
# CET is strictly UTC+1 and Paris is on CEST by then. dateparser reads the
# abbreviation literally and lands an hour early, which is worse than saying
# nothing at all. UTC and GMT are the exception, they mean the offset.
#
# Deliberately missing: IST (India, Israel and Ireland all claim it) and
# anything else where guessing wrong is likely. CST is read as Chicago,
# which is the common usage here but not China Standard Time.
ZONE_ALIASES = {
    "UTC": "UTC",
    "GMT": "UTC",
    "BST": "Europe/London",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "WET": "Europe/Lisbon",
    "WEST": "Europe/Lisbon",
    "EET": "Europe/Athens",
    "EEST": "Europe/Athens",
    "MSK": "Europe/Moscow",
    "ET": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CT": "America/Chicago",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MT": "America/Denver",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "NZST": "Pacific/Auckland",
    "NZDT": "Pacific/Auckland",
}

# Three letters and up are distinctive enough to read in any case ("8pm est").
# The two letter ones are ordinary words elsewhere, and "19:00 et 20:00" is
# French for "19:00 and 20:00", so those only count shouted.
_LONG = sorted((z for z in ZONE_ALIASES if len(z) > 2), key=len, reverse=True)
_SHORT = sorted(z for z in ZONE_ALIASES if len(z) == 2)
ZONE_NAME = re.compile(
    r"\b(?:(?i:" + "|".join(_LONG) + r")|" + "|".join(_SHORT) + r")\b"
)
# "19:00 UTC+2", "8pm GMT-5", "14:00 UTC+05:30"
ZONE_OFFSET = re.compile(r"\b(?:UTC|GMT)\s*([+-])\s*([01]?\d)(?::?([0-5]\d))?\b")

# how far from a time a zone name may sit and still be describing it, enough
# for "22:00 CET" and "22:00 (CET)" but not a stray "PT" later in a sentence
ZONE_NEAR = 4

MAX_MATCHES = 3

# anything closer than this is happening "now-ish" for everyone in the
# conversation, converting it just adds noise
MIN_LEAD = timedelta(hours=1)


def explicit_zone(text: str) -> tzinfo | None:
    """Return the timezone a message states for its own times, if any.

    A message carrying its own zone ("22:00 CET") is readable by everyone
    without knowing who wrote it, so the caller can convert it whether or
    not the author has registered a timezone. Only a zone sitting next to a
    time counts, so "the 19:00 PT stream" resolves but "I ride the CET line"
    does not.
    """
    spans = [m.span() for m in TIME_OF_DAY.finditer(text)]
    if not spans:
        return None

    def beside_a_time(start: int, end: int) -> bool:
        return any(
            start - t_end <= ZONE_NEAR and t_start - end <= ZONE_NEAR
            for t_start, t_end in spans
        )

    # offsets first, "UTC+2" would otherwise match the bare "UTC" alias
    for m in ZONE_OFFSET.finditer(text):
        if beside_a_time(*m.span()):
            sign, hours, minutes = m.groups()
            delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
            return timezone(-delta if sign == "-" else delta)

    for m in ZONE_NAME.finditer(text):
        if beside_a_time(*m.span()):
            return ZoneInfo(ZONE_ALIASES[m.group(0).upper()])
    return None


def extract_times(
    text: str, tz: tzinfo | None, now: datetime | None = None
) -> list[TimeMatch]:
    """Return up to MAX_MATCHES concrete times found in text.

    tz is the zone the author's bare times are read in, and may be None
    when their timezone is unknown: a message that states its own zone
    still resolves, anything else comes back empty.

    Times less than MIN_LEAD ahead of now are dropped, close enough that
    a conversion helps nobody.

    now anchors relative phrases ("in 45 minutes") and future preference,
    mainly so tests can pin it. Defaults to the current time.
    """
    if "<t:" in text:
        return []
    if not TIME_OF_DAY.search(text):
        return []

    # a zone the author spelled out beats the one they registered, that is
    # the whole point of typing it
    stated = explicit_zone(text)
    tz = stated or tz
    if tz is None:
        return []

    text = COMPACT_24H_AT.sub(r"\g<1>\g<2>:\g<3>", text)
    text = COMPACT_24H_HRS.sub(r"\g<1>:\g<2>", text)
    if stated is not None:
        # blank the zone so dateparser doesn't apply the abbreviation's
        # literal offset on top of the zone it already resolved to
        text = ZONE_OFFSET.sub(lambda m: " " * len(m.group(0)), text)
        text = ZONE_NAME.sub(lambda m: " " * len(m.group(0)), text)

    if now is None:
        now = datetime.now(tz)
    now = now.astimezone(tz)

    matches: list[TimeMatch] = []
    seen: set[int] = set()

    def relative(m: re.Match) -> str:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        delta = timedelta(hours=amount) if unit.startswith("h") else timedelta(
            minutes=amount
        )
        when = now + delta
        unix = int(when.timestamp())
        if delta >= MIN_LEAD and unix not in seen and len(matches) < MAX_MATCHES:
            seen.add(unix)
            matches.append(TimeMatch(m.group(0), when))
        # blank the span so dateparser doesn't parse it again
        return " " * len(m.group(0))

    text = RELATIVE_IN.sub(relative, text)

    if TIME_OF_DAY.search(text):
        # dateparser's future preference for bare times compares the parsed
        # time converted to UTC against RELATIVE_BASE, so the base must be
        # naive UTC (its own default), not wall-clock in the target zone
        base = now.astimezone(timezone.utc).replace(tzinfo=None)
        found = search_dates(
            text,
            languages=["en"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": str(tz),
                "RELATIVE_BASE": base,
                # search_dates runs full-text language detection first and
                # drops the message outright if it can't name a language.
                # A message that is only a time ("7pm", "21:00?") has no
                # detectable language, and the languages= list above is only
                # consulted as a fallback when it holds more than one entry,
                # so those never reached the parser at all. This is the
                # documented way to say "assume English when unsure".
                "DEFAULT_LANGUAGES": ["en"],
            },
        )
    else:
        found = None

    for phrase, when in found or []:
        if len(matches) == MAX_MATCHES:
            break
        # search_dates happily matches bare numbers and weekdays,
        # only keep phrases that carry an actual time of day
        if not TIME_OF_DAY.search(phrase):
            continue
        when = when.astimezone(tz)
        if when - now < MIN_LEAD:
            continue
        unix = int(when.timestamp())
        if unix in seen:
            continue
        seen.add(unix)
        matches.append(TimeMatch(phrase.strip(), when))
    return matches
