"""What the note writer and the profile writer are asked, and how their replies are read.

After an exchange, `Mneme.aobserve` (or `acapture`) asks the decision chain a cheap yes/no first (`WORTH`: did they
share anything worth remembering?), so the note writer is only called when there is something to write. The
writer is the host's `complete` function, which can be a fixed, cheap model whatever model the conversation runs
on, so the notes stay the same quality when the chat model changes; with the unify tier on, it also gives each
note in the unifying language. `Mneme.areflect` has it rewrite the short profile card from the notes. This module
only builds the prompts (their wording is in `prompts.py`, or the companion's config) and reads the replies; `Mneme`
makes the calls.
"""

from __future__ import annotations

from datetime import tzinfo

from typing import Mapping

from . import dates
from .decide import Predicate
from .i18n import fill
from .memory import note_fields
from .prompts import PROMPTS
from .providers import json_in

WORTH_NAME = "worth_remembering"


def worth(instructions: str = PROMPTS["worth"]) -> Predicate:
    """The yes/no question asked before the note writer: did they share anything worth remembering?"""
    return Predicate(WORTH_NAME, instructions)


WORTH = worth()  # with the built-in wording


def writer_prompt(user_name: str, known: list[str], today: str, gloss_language: str | None = None, *,
                  prompts: Mapping[str, str] = PROMPTS) -> str:
    """The note writer's system prompt (`prompts["note_writer"]`); the exchange itself is the user message."""
    gloss = fill(prompts["note_gloss"], language=gloss_language) if gloss_language else ""
    return fill(prompts["note_writer"], user=user_name, known="\n".join(f"- {text}" for text in known) or "-",
                gloss=gloss, today=today)


def notes_in(reply: str, now: float, zone: tzinfo | None) -> list[dict]:
    """The writer's reply as note fields for `Memory.keep` (at most three), each held to the rules of writing: a
    field of the wrong type is dropped, an item without text is skipped. A plan's day comes from its `date`, or
    else from a day written in its sentence, the first such day from today on."""
    items = json_in(reply, "[")
    found = []
    for item in items[:3] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        happened = dates.noon(item["date"], zone) if isinstance(item.get("date"), str) else None
        if happened is None and kind == "plan" and isinstance(item.get("text"), str):
            happened = dates.find(item["text"], now, zone, ahead=True)  # writers often put the day in the sentence
        fields = note_fields(item.get("text"), kind=kind, key=item.get("key"), importance=item.get("importance", 2),
                             feeling=item.get("feeling", 0.0), happened_at=happened, gloss=item.get("gloss"),
                             strict=False)
        if fields is not None:
            found.append(fields)
    return found


def reflect_prompt(user_name: str, companion_name: str, language: str, notes, *,
                   prompts: Mapping[str, str] = PROMPTS) -> str:
    """The profile writer's system prompt (`prompts["reflect"]`), over the most important and newest notes."""
    listing = "\n".join(f"- ({note.kind}) {note.text}" for note in notes)
    return fill(prompts["reflect"], user=user_name, name=companion_name, lang=language, notes=listing)
