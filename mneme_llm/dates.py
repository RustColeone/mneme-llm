"""Dates the way a person says them: "yesterday", "in 3 days", "last year 09-17" (or 昨天, 3天后, 去年 09-17).

Models are bad at date arithmetic; telling them "last year 09-17" instead of a timestamp keeps "that was a while
ago" obvious. Times are shown in the zone you pass (the person's own, ideally), the machine's zone otherwise.
"""

from __future__ import annotations

from datetime import datetime, tzinfo

WORDS = {
    "en": {"today": "today", "yesterday": "yesterday", "days": "{n} days ago", "last_year": "last year {md}",
           "tomorrow": "tomorrow", "after": "the day after tomorrow", "in_days": "in {n} days",
           "next_year": "next year {md}"},
    "zh": {"today": "今天", "yesterday": "昨天", "days": "{n}天前", "last_year": "去年 {md}",
           "tomorrow": "明天", "after": "后天", "in_days": "{n}天后", "next_year": "明年 {md}"},
}


def local(timestamp: float, zone: tzinfo | None = None) -> datetime:
    return datetime.fromtimestamp(timestamp, zone) if zone else datetime.fromtimestamp(timestamp).astimezone()


def when(timestamp: float, now: float, zone: tzinfo | None = None, lang: str = "en") -> str:
    """When `timestamp` is, relative to `now`, in calendar days of `zone` (past or future)."""
    words = WORDS.get(lang, WORDS["en"])
    then, today = local(timestamp, zone), local(now, zone)
    days = (today.date() - then.date()).days
    if days < 0:
        ahead = -days
        if ahead == 1:
            return words["tomorrow"]
        if ahead == 2:
            return words["after"]
        if ahead < 7:
            return words["in_days"].format(n=ahead)
        if then.year == today.year:
            return then.strftime("%m-%d")
        if then.year == today.year + 1:
            return words["next_year"].format(md=then.strftime("%m-%d"))
        return then.strftime("%Y-%m-%d")
    if days == 0:
        return words["today"]
    if days == 1:
        return words["yesterday"]
    if days < 7:
        return words["days"].format(n=days)
    md = then.strftime("%m-%d")
    if then.year == today.year:
        return md
    if then.year == today.year - 1:
        return words["last_year"].format(md=md)
    return then.strftime("%Y-%m-%d")


def stamp(timestamp: float, zone: tzinfo | None = None) -> str:
    """An exact local time, for logs and listings."""
    return local(timestamp, zone).strftime("%Y-%m-%d %H:%M")
