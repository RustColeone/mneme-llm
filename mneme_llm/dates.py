"""Dates the way a person says them: "yesterday", "in 3 days", "last year 09-17" (or 昨天, 3天后, 去年 09-17).

Models are bad at date arithmetic; telling them "last year 09-17" instead of a timestamp keeps "that was a while
ago" obvious. Times are shown in the zone you pass (the person's own, ideally), the machine's zone otherwise.
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, tzinfo

from .i18n import say


def local(timestamp: float, zone: tzinfo | None = None) -> datetime:
    return datetime.fromtimestamp(timestamp, zone) if zone else datetime.fromtimestamp(timestamp).astimezone()


def when(timestamp: float, now: float, zone: tzinfo | None = None, lang: str = "en") -> str:
    """When `timestamp` is, relative to `now`, in calendar days of `zone` (past or future)."""
    then, today = local(timestamp, zone), local(now, zone)
    days = (today.date() - then.date()).days
    if days < 0:
        ahead = -days
        if ahead == 1:
            return say(lang, "date.tomorrow")
        if ahead == 2:
            return say(lang, "date.after")
        if ahead < 7:
            return say(lang, "date.in_days", n=ahead)
        if then.year == today.year:
            return then.strftime("%m-%d")
        if then.year == today.year + 1:
            return say(lang, "date.next_year", md=then.strftime("%m-%d"))
        return then.strftime("%Y-%m-%d")
    if days == 0:
        return say(lang, "date.today")
    if days == 1:
        return say(lang, "date.yesterday")
    if days < 7:
        return say(lang, "date.days", n=days)
    md = then.strftime("%m-%d")
    if then.year == today.year:
        return md
    if then.year == today.year - 1:
        return say(lang, "date.last_year", md=md)
    return then.strftime("%Y-%m-%d")


LATEST = 32503680000.0  # 3000-01-01: later "times" are mistakes (milliseconds, say), and not every platform shows them


def seconds(value) -> float | None:
    """`value` as a time in seconds between 1970 and the year 3000, or None when it is no such time."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and 0 <= value < LATEST else None


def stamp(timestamp: float, zone: tzinfo | None = None) -> str:
    """An exact local time, for logs and listings."""
    return local(timestamp, zone).strftime("%Y-%m-%d %H:%M")


def noon(day: str, zone: tzinfo | None = None) -> float | None:
    """Noon of a "YYYY-MM-DD" in the person's zone (the machine's when none is given); None if it is no date."""
    try:
        parsed = datetime.strptime(str(day or "")[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return _noon(parsed.year, parsed.month, parsed.day, zone)


def _noon(year: int, month: int, day: int, zone: tzinfo | None) -> float | None:
    try:
        moment = datetime(year, month, day, 12, tzinfo=zone) if zone else datetime(year, month, day, 12)
        return seconds(moment.timestamp())  # (year 1, or before 1970 on Windows, has no timestamp)
    except (ValueError, OverflowError, OSError):
        return None


def find(text: str, now: float | None = None, zone: tzinfo | None = None, *, ahead: bool = False) -> float | None:
    """Noon (in `zone`) of the first date written in `text`: 2026-10-30, 2026/10/30, 2026年10月30日, or 10月30日,
    which means the nearest such day to `now` (so "1月3日" written on 28 December is next January), or with `ahead`
    (for plans) the first such day from today on; None when there is none. Digits around a date (a number such
    as 12026-10-301) are not a date."""
    found = re.search(r"(?<!\d)(20\d\d)(?:[-/](\d{1,2})[-/](\d{1,2})|年(\d{1,2})月(\d{1,2})[日号]?)(?!\d)", text)
    if found:
        year = int(found.group(1))
        month, day = (int(found.group(2) or found.group(4)), int(found.group(3) or found.group(5)))
        return _noon(year, month, day, zone)
    found = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})[日号]", text)
    if not found:
        return None
    month, day = int(found.group(1)), int(found.group(2))
    now = time.time() if now is None else now
    this_year = local(now, zone).year
    candidates = [moment for moment in (_noon(year, month, day, zone) for year in (this_year - 1, this_year,
                                                                                    this_year + 1)) if moment]
    if ahead:
        today = local(now, zone)
        start = _noon(today.year, today.month, today.day, zone)
        return min((moment for moment in candidates if moment >= start), default=None)
    return min(candidates, key=lambda moment: abs(moment - now)) if candidates else None
