"""An exchange (one turn of a conversation) as the judges and the note writer read it."""

from __future__ import annotations

from typing import Mapping

from .i18n import fill
from .prompts import PROMPTS


def as_lines(exchange) -> list[tuple[str, str]]:
    """An exchange as `(who, said)` pairs: a string is one line by nobody in particular; a list of pairs or of chat
    messages (`{"role" or "name": ..., "content": ...}`) is one line each."""
    if isinstance(exchange, str):
        return [("", exchange)]
    if exchange is None or isinstance(exchange, (bytes, dict)) or not hasattr(exchange, "__iter__"):
        raise TypeError("an exchange is a string, or a list of (who, said) pairs or of chat messages")
    lines = []
    for item in exchange:
        if isinstance(item, dict):
            who, said = item.get("name") or item.get("role") or "", item.get("content")
            if isinstance(said, list):  # content given as parts: keep the text ones
                said = " ".join(part.get("text", "") for part in said if isinstance(part, dict))
        else:
            who, said = item
        lines.append((str(who or ""), "" if said is None else str(said)))
    return lines


def text_of(lines) -> str:
    return "\n".join(f"{who}: {said}" if who else said for who, said in lines)


def as_text(exchange) -> str:
    """An exchange as one text: a string as it is, or a list of `(who, said)` pairs or of chat messages
    (`{"role" or "name": ..., "content": ...}`), one line each."""
    return exchange if isinstance(exchange, str) else text_of(as_lines(exchange))


def frame(exchange, *, source: str = "user", user_name: str = "the user", companion_name: str = "the assistant",
          prompts: Mapping[str, str] = PROMPTS) -> str:
    """What a judge reads: who is who and who started it (`prompts["frame"]`, `started_user` …), then the
    exchange. The questions name nobody, so one learned model serves every person; the names are said here instead."""
    names = {"user": user_name, "assistant": companion_name}
    started = {"user": "started_user", "speak-up": "started_speak_up", "duty": "started_duty"}.get(source)
    said = fill(prompts[started], **names) if started else ""
    return fill(prompts["frame"], started=said, **names) + "\n" + as_text(exchange)
