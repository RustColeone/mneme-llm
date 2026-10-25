"""Keeping notes without the model having to call a tool: ask after each exchange, write what is worth keeping.

    notes = await acapture(m, "discord:42", exchange, user="小明")
    card  = await areflect(m, "discord:42", user="小明")      # e.g. nightly

Capture asks the decision chain a cheap yes/no first ("did they share anything worth remembering?"), so the
chat model is only asked to write notes when there is something to write. Reflection rewrites the short
profile card from the notes. Both use the `complete` function the Mneme was given.
"""

from __future__ import annotations

import inspect
import json
import re

from .decide import Predicate
from .memory import KINDS

WORTH = Predicate("worth_remembering",
                  "In this exchange the user shared something about themselves worth remembering in later "
                  "conversations: a fact about their life, a preference, a plan, or something that happened to "
                  "them (not small talk, not a question about the world).")

CAPTURE = """From the exchange below, write down what is worth remembering about {user} for later conversations.
Reply with only a JSON list (possibly empty). Each item: {{"text": one sentence in {user}'s language, "kind": one of
{kinds}, "key": optional "topic.aspect" for facts that can change (never the value itself), "importance": 1-5,
"feeling": -1..1 how {user} felt about it}}. At most 3 items; leave out what is already known:
{known}"""

REFLECT = """Write a short impression of {user} as {name} knows them (at most 4 sentences, in {lang}), from these
notes. Who they are, what matters to them now, how to be with them. Reply with only the impression.
{notes}"""


async def _complete(mneme, system: str, user: str) -> str:
    complete = mneme.complete
    if complete is None:
        raise RuntimeError("capture and reflect need the Mneme to have a `complete` function")
    reply = complete(system, user)
    if inspect.isawaitable(reply):
        reply = await reply
    return str(reply or "")


async def acapture(mneme, subject: str, exchange, *, user: str = "the user", gate: float = 0.5) -> list:
    """Notes kept from one exchange (source "auto", so the daily quota applies)."""
    if not isinstance(exchange, str):
        exchange = "\n".join(f"{who}: {said}" for who, said in exchange)
    if mneme.decider.tiers and gate > 0:
        answers = await mneme.decider.adecide(exchange, [WORTH])
        worth = answers.get("worth_remembering")
        if worth is not None and worth.probability < gate:
            return []
    known = "\n".join(f"- {note.text}" for note in mneme.memory.recall(subject, exchange, log=False).chosen) or "-"
    reply = await _complete(mneme, CAPTURE.format(user=user, kinds=", ".join(KINDS), known=known), exchange)
    found = re.search(r"\[.*\]", reply, re.S)
    if not found:
        return []
    try:
        items = json.loads(found.group(0))
    except json.JSONDecodeError:
        return []
    kept = []
    for item in items[:3] if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        try:
            note = mneme.memory.remember(subject, str(item["text"]), kind=str(item.get("kind", "episode")),
                                         key=item.get("key") or None, importance=int(item.get("importance", 2)),
                                         feeling=float(item.get("feeling", 0) or 0), source="auto")
        except (TypeError, ValueError):
            continue
        if note is not None:
            kept.append(note)
    return kept


async def areflect(mneme, subject: str, *, user: str = "the user", limit: int = 60) -> str | None:
    """Rewrite the profile card from the most important and newest notes; returns the new card."""
    notes = mneme.memory.notes(subject)
    if not notes:
        return None
    notes = sorted(notes, key=lambda note: (-note.importance, -note.id))[:limit]
    listing = "\n".join(f"- ({note.kind}) {note.text}" for note in notes)
    lang = "Chinese" if mneme.lang == "zh" else "the language of the notes"
    card = (await _complete(mneme, REFLECT.format(user=user, name=mneme.name, lang=lang, notes=listing),
                            "Write the impression now.")).strip()
    if card:
        mneme.memory.set_profile(subject, card)
    return card or None
