"""One person under several subjects: the accounts a person reaches the companion by ("discord:42", "web:leo"), kept
as one.

    link        `link("web:leo", "discord:42")`: from then on "web:leo" is "discord:42" in every call (notes, mood,
                role, alias, profile card), and what was kept under "web:leo" joins what is kept under "discord:42".
                Set by the host, never by a model: the host knows who is behind each account (a login, the
                owner's own accounts)
    joining     notes are put together under the rules writing keeps (one live note per key, the newest; no text
                twice), and so are the recall logs and the mood's timelines; of two relationships the closer one is
                kept (since the earlier day), of two moods, profile cards or aliases the newer
    unlink      the subject is its own again from then on; what was joined stays with the person

Links are kept one step deep: a subject always points at a person's own subject, never at another link.
"""

from __future__ import annotations

import time
from typing import Callable

from . import text as texts
from .store import Store


class People:
    def __init__(self, store: Store, space: str, *, clock: Callable[[], float] = time.time):
        self.store, self.space, self.clock = store, space, clock

    # ---- reading -------------------------------------------------------------------------------------
    def of(self, subject: str) -> str:
        """The person a subject stands for: the subject it is linked to, or itself."""
        if not isinstance(subject, str):
            return subject  # (the caller's own checks say what is wrong with it)
        row = self.store.row("select person from people where space = ? and subject = ?", (self.space, subject))
        return row["person"] if row is not None else subject

    def subjects(self, subject: str) -> list[str]:
        """Every subject the person goes by: their own first, then the ones linked to them."""
        person = self.of(subject)
        return [person] + [row["subject"] for row in self.store.rows(
            "select subject from people where space = ? and person = ? order by subject", (self.space, person))]

    def all(self) -> dict[str, str]:
        """Every link, subject → person."""
        return {row["subject"]: row["person"] for row in self.store.rows(
            "select subject, person from people where space = ? order by person, subject", (self.space,))}

    # ---- changing ------------------------------------------------------------------------------------
    def link(self, subject: str, person: str) -> tuple[str, bool]:
        """Record that `subject` is the same person as `person` (the host's call, never a model's). Returns the
        person's own subject, and whether this was new (the caller then joins what each kept). A subject linked to
        someone else already must be unlinked first; the subjects linked to `subject` follow it."""
        texts.required(subject, "subject")
        texts.required(person, "person")
        with self.store.transaction():
            person = self.of(person)
            if person == subject or self.of(subject) == person:
                return person, False  # already one person
            other = self.of(subject)
            if other != subject:
                raise ValueError(f"{subject} is linked to {other}; unlink it first")
            now = self.clock()
            self.store.execute("update people set person = ?, updated_at = ? where space = ? and person = ?",
                               (person, now, self.space, subject))
            self.store.execute("insert into people (space, subject, person, updated_at) values (?, ?, ?, ?)",
                               (self.space, subject, person, now))
        return person, True

    def unlink(self, subject: str) -> bool:
        return bool(self.store.execute("delete from people where space = ? and subject = ?",
                                       (self.space, subject)).rowcount)

    def remove(self, subject: str) -> int:
        """Every link of the person the subject stands for (for `erase`); returns how many there were."""
        person = self.of(subject)
        return self.store.execute("delete from people where space = ? and (person = ? or subject = ?)",
                                  (self.space, person, person)).rowcount

    # ---- moving between files ------------------------------------------------------------------------
    def export_rows(self) -> dict:
        return {"people": [dict(row) for row in self.store.rows(
            "select * from people where space = ? order by rowid", (self.space,))]}

    def rows_of(self, rows=()) -> list[tuple[str, str]]:
        """The (subject, person) pairs of exported links; a row without both is skipped."""
        return [(row["subject"], row["person"]) for row in rows if isinstance(row, dict) and
                all(isinstance(row.get(name), str) and row[name].strip() for name in ("subject", "person"))]


class Resolves:
    """For a part that keeps rows by subject: `who(subject)` is the person it stands for (itself without links)."""
    people: People | None = None

    def who(self, subject: str) -> str:
        return self.people.of(subject) if self.people is not None else subject
