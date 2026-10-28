"""What each person calls the companion: a name of their own for it, beside the name it has for everyone.

    alias       one per person ("鲸酱" for Leo, while the companion's own name stays 大肥鱼 for everyone else), at
                most 40 characters on one line. Set by the host, never by a model: the person chooses it in the
                host's interface, or says so and the host's code records it
    telling     `line()` says it for the system prompt ("(Leo calls you 鲸酱.)")
"""

from __future__ import annotations

import time
from typing import Callable

from . import dates, text as texts
from .i18n import Speaks, Words, say
from .people import People, Resolves
from .store import Store

LIMIT = 40  # characters: a name, not a sentence (it goes into every prompt for that person)


class Aliases(Speaks, Resolves):
    def __init__(self, store: Store, space: str, *, display_language: str | Words = "en",
                 people: People | None = None, clock: Callable[[], float] = time.time):
        self.store, self.space, self.people, self.clock = store, space, people, clock
        self.words = Words.of(display_language)

    # ---- reading -------------------------------------------------------------------------------------
    def get(self, subject: str) -> str | None:
        subject = self.who(subject)
        row = self.store.row("select alias from aliases where space = ? and subject = ?", (self.space, subject))
        return row["alias"] if row is not None else None

    def all(self) -> dict[str, str]:
        """Every person's alias for the companion, by subject."""
        return {row["subject"]: row["alias"] for row in self.store.rows(
            "select subject, alias from aliases where space = ? order by subject", (self.space,))}

    def line(self, subject: str, user_name: str | None = None) -> str:
        """What the person calls the companion, for the system prompt ("" for a person without an alias)."""
        alias = self.get(subject)
        return say(self.words, "alias.line", who=user_name or subject, alias=alias) if alias else ""

    # ---- changing ------------------------------------------------------------------------------------
    def set(self, subject: str, alias: str) -> str:
        """Record what the person calls the companion (the host's call, never a model's): cleaned onto one line and
        cut to 40 characters. Returns the alias as stored."""
        texts.required(subject, "subject")
        texts.required(alias, "alias")
        alias = texts.clip(alias, LIMIT)
        if texts.blank(alias):
            raise ValueError("alias must not be empty")
        with self.writing(subject) as subject:
            self.store.execute("insert or replace into aliases (space, subject, alias, updated_at) values "
                               "(?, ?, ?, ?)", (self.space, subject, alias, self.clock()))
        return alias

    def remove(self, subject: str) -> bool:
        with self.writing(subject) as subject:
            return bool(self.store.execute("delete from aliases where space = ? and subject = ?",
                                           (self.space, subject)).rowcount)

    def join(self, old: str, new: str) -> None:
        """`old` is the person `new` now (`People.link`): of two aliases the newer is kept."""
        with self.store.transaction():
            rows = {row["subject"]: row for row in self.store.rows(
                "select * from aliases where space = ? and subject in (?, ?)", (self.space, old, new))}
            if old in rows and (new not in rows or rows[old]["updated_at"] > rows[new]["updated_at"]):
                self.store.execute("insert or replace into aliases (space, subject, alias, updated_at) values "
                                   "(?, ?, ?, ?)", (self.space, new, rows[old]["alias"], rows[old]["updated_at"]))
            self.store.execute("delete from aliases where space = ? and subject = ?", (self.space, old))

    # ---- moving between files ------------------------------------------------------------------------
    def export_rows(self) -> dict:
        return {"aliases": [dict(row) for row in self.store.rows(
            "select * from aliases where space = ? order by rowid", (self.space,))]}

    def import_rows(self, rows=()) -> None:
        """Add exported aliases to this space, replacing a person's present one; an alias is held to the same rule
        as `set` (one line, 40 characters), and a row without a subject or an alias is skipped."""
        now = self.clock()
        with self.store.transaction():
            for row in rows:
                if not isinstance(row, dict):
                    continue
                subject, alias = row.get("subject"), row.get("alias")
                if not isinstance(subject, str) or not subject.strip() or not isinstance(alias, str):
                    continue
                alias = texts.clip(alias, LIMIT)
                if texts.blank(alias):
                    continue
                updated = dates.seconds(row.get("updated_at"))
                self.store.execute(
                    "insert or replace into aliases (space, subject, alias, updated_at) values (?, ?, ?, ?)",
                    (self.space, subject, alias, now if updated is None else min(now, updated)))
