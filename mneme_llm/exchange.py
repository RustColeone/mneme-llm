"""An exchange (one turn of a conversation) as the judges and the note writer read it."""

from __future__ import annotations


def as_text(exchange) -> str:
    """An exchange as one text: a string as it is, or a list of `(who, said)` pairs or of chat messages
    (`{"role" or "name": ..., "content": ...}`), one line each."""
    if isinstance(exchange, str):
        return exchange
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
        lines.append(f"{who}: {said}" if who else str(said))
    return "\n".join(lines)


def frame(exchange, *, source: str = "user", user_name: str = "the user",
          companion_name: str = "the assistant") -> str:
    """What a judge reads: who is who and who started it, then the exchange. The questions name nobody, so one
    learned model serves every person; the names are said here instead."""
    user, assistant = user_name, companion_name
    started = {"user": f"{user} is talking to {assistant}.",
               "speak-up": f"{assistant} reached out to {user} on their own, because they wanted to (not as a task).",
               "duty": f"{assistant} is doing a scheduled task."}.get(source, "")
    return f"[{started} The assistant is {assistant}; the user is {user}.]\n{as_text(exchange)}"
