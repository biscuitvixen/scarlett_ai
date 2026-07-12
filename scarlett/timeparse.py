"""Finds concrete times in chat messages.

Deterministic only. A cheap regex gate decides whether a message contains
an explicit time of day at all, then dateparser resolves the phrases in
the author's timezone. Bare dates ("friday") are ignored on purpose: a
timestamp without an hour does not help anyone coordinate, and requiring
a clock time kills most false positives (prices, scores, "may", "sat").
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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

MAX_MATCHES = 3


def extract_times(
    text: str, tz: ZoneInfo, now: datetime | None = None
) -> list[TimeMatch]:
    """Return up to MAX_MATCHES concrete times found in text.

    now anchors relative phrases ("in 45 minutes") and future preference,
    mainly so tests can pin it. Defaults to the current time.
    """
    if "<t:" in text:
        return []
    if not TIME_OF_DAY.search(text):
        return []

    text = COMPACT_24H_AT.sub(r"\g<1>\g<2>:\g<3>", text)
    text = COMPACT_24H_HRS.sub(r"\g<1>:\g<2>", text)

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
        if unix not in seen and len(matches) < MAX_MATCHES:
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
        unix = int(when.timestamp())
        if unix in seen:
            continue
        seen.add(unix)
        matches.append(TimeMatch(phrase.strip(), when))
    return matches
