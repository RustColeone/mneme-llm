"""Memories about people: written as short notes, recalled by evidence, rendered with human dates.

A note is one sentence about a subject ("Has a cat named 年糕"). Kinds say how it ages:

    fact, preference    lasting; never fade ("lives in Shanghai", "hates coriander")
    episode, plan       fade with a half-life (30 days by default) unless recalled again
    reflection          the companion's own impression; fades like an episode

A `key` ("user.city", "cat.name": what the note is about, never its value) makes a newer note replace the older
one, and the old version stays in the history. Recall scores each note by evidence (query terms it shares,
weighted by how rare they are among this person's notes) times freshness, importance and feeling, then fills a
small budget; every recall can explain what was chosen and what was skipped and why.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Callable, Iterable

from . import dates, text as texts
from .store import Store, dumps

KINDS = ("fact", "preference", "episode", "plan", "reflection")
LASTING = frozenset({"fact", "preference"})
KEY = re.compile(r"^[\w㐀-鿿]+(\.[\w㐀-鿿]+){0,3}$")
MAX_KEY = 48
MAX_TEXT = 500
PINNED = 5  # importance at which a note is always in context


@dataclass(frozen=True)
class Note:
    id: int
    subject: str
    text: str
    kind: str
    key: str | None
    importance: int
    feeling: float
    happened_at: float
    created_at: float
    recalls: int
    source: str | None
    recalled_at: float | None = None
    superseded_by: int | None = None
    deleted_at: float | None = None

    @classmethod
    def of(cls, row) -> "Note":
        return cls(row["id"], row["subject"], row["text"], row["kind"], row["key"], row["importance"], row["feeling"],
                   row["happened_at"], row["created_at"], row["recalls"], row["source"], row["recalled_at"],
                   row["superseded_by"], row["deleted_at"])

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "kind": self.kind, "key": self.key, "importance": self.importance,
                "feeling": self.feeling, "happened_at": self.happened_at, "created_at": self.created_at}


@dataclass(frozen=True)
class Recalled:
    note: Note
    score: float
    why: str                      # "pinned", "matched: 考试, 复习" or "recent"
    matched: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recall:
    query: str
    chosen: list[Recalled]
    skipped: list[tuple[Note, str]] = field(default_factory=list)  # (note, reason) for the closest misses

    def explain(self) -> str:
        lines = [f"recall for {self.query!r}:"]
        lines += [f"  + #{r.note.id} {r.why} (score {r.score:.2f}): {texts.clip(r.note.text, 70)}" for r in self.chosen]
        lines += [f"  - #{note.id} {reason}: {texts.clip(note.text, 70)}" for note, reason in self.skipped]
        return "\n".join(lines)


class Memory:
    """The notes of one space. Every method takes the subject the note is about."""

    def __init__(self, store: Store, space: str, *, half_life_days: float = 30.0, daily_quota: int = 8,
                 max_notes: int = 5000, zone: tzinfo | None = None, lang: str = "en",
                 clock: Callable[[], float] = time.time):
        self.store, self.space = store, space
        self.half_life_days, self.daily_quota, self.max_notes = half_life_days, daily_quota, max_notes
        self.zone, self.lang, self.clock = zone, lang, clock

    # ---- writing ---------------------------------------------------------------------------------
    def remember(self, subject: str, text: str, **options) -> Note | None:
        """Keep a note; returns it (or the existing note it repeats), or None when an automatic note is over quota.

        `source="auto"` marks notes a model chose to keep without being asked; at most `daily_quota` of those per
        subject per day are kept unless they are important (4+). Anything else (the person asked, an import)
        always lands.
        """
        return self.keep(subject, text, **options)[1]

    def keep(self, subject: str, text: str, *, kind: str = "episode", key: str | None = None,
             importance: int = 2, feeling: float = 0.0, happened_at: float | None = None,
             source: str | None = None) -> tuple[str, Note | None]:
        """`remember`, also saying what happened: "kept", "replaced" (a key's older note), "known" (the same
        text was already there) or "over quota"."""
        text = texts.clip(text, MAX_TEXT)
        if not text:
            raise ValueError("a memory needs some text")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        if key is not None:
            key = key.strip().lower() or None
            if key is not None and (len(key) > MAX_KEY or not KEY.match(key)):
                raise ValueError("a key names what the note is about, like 'user.city' or 'cat.name' (no spaces, "
                                 "at most 4 parts); the value goes in the text")
        importance = max(1, min(5, int(importance)))
        feeling = max(-1.0, min(1.0, float(feeling)))
        now = self.clock()
        happened_at = now if happened_at is None else float(happened_at)
        with self.store.transaction():
            same = self._live_where(subject, "lower(text) = lower(?)", (text,))
            if same:
                note = same[0]
                self.store.execute("update memories set importance = max(importance, ?) where id = ?",
                                   (importance, note.id))
                return "known", self.get(note.id)
            if source == "auto" and importance < 4 and self._auto_today(subject, now) >= self.daily_quota:
                return "over quota", None
            cursor = self.store.execute(
                "insert into memories (space, subject, key, kind, text, importance, feeling, happened_at, created_at,"
                " source) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.space, subject, key, kind, text, importance, feeling, happened_at, now, source))
            new = cursor.lastrowid
            replaced = 0
            if key is not None:
                replaced = self.store.execute(
                    "update memories set superseded_by = ? where space = ? and subject = ? and key = ? and id != ? and"
                    " superseded_by is null and deleted_at is null", (new, self.space, subject, key, new)).rowcount
            self._prune(subject, now)
        return ("replaced" if replaced else "kept"), self.get(new)

    def forget(self, subject: str, *, id: int | None = None, key: str | None = None) -> int:
        """Remove a note (by id) or the live note of a key; returns how many were removed. History stays on disk
        (soft delete) until `purge`."""
        if (id is None) == (key is None):
            raise ValueError("forget takes exactly one of id or key")
        where, value = ("id = ?", id) if id is not None else ("key = ?", key.strip().lower())
        cursor = self.store.execute(f"update memories set deleted_at = ? where space = ? and subject = ? and {where}"
                                    " and deleted_at is null and superseded_by is null",
                                    (self.clock(), self.space, subject, value))
        return cursor.rowcount

    def purge(self, subject: str | None = None) -> int:
        """Erase removed and replaced notes for good (all subjects when none is given)."""
        sql = "delete from memories where space = ? and (deleted_at is not null or superseded_by is not null)"
        parameters: tuple = (self.space,)
        if subject is not None:
            sql, parameters = sql + " and subject = ?", (self.space, subject)
        return self.store.execute(sql, parameters).rowcount

    def erase(self, subject: str) -> int:
        """Everything about a subject, gone: notes, history, profile, mood (for "forget me")."""
        with self.store.transaction():
            count = self.store.execute("delete from memories where space = ? and subject = ?",
                                       (self.space, subject)).rowcount
            for table in ("recalls", "profiles", "moods", "mood_events"):
                self.store.execute(f"delete from {table} where space = ? and subject = ?", (self.space, subject))
        return count

    # ---- reading ---------------------------------------------------------------------------------
    def get(self, id: int) -> Note | None:
        row = self.store.row("select * from memories where id = ? and space = ?", (id, self.space))
        return Note.of(row) if row else None

    def notes(self, subject: str, *, kinds: Iterable[str] | None = None) -> list[Note]:
        """The live notes of a subject, newest first."""
        found = self._live_where(subject)
        if kinds is not None:
            wanted = set(kinds)
            found = [note for note in found if note.kind in wanted]
        return found

    def history(self, subject: str, key: str) -> list[Note]:
        """Every version a key has had, oldest first (the last is live unless it was forgotten)."""
        rows = self.store.rows("select * from memories where space = ? and subject = ? and key = ? order by id",
                               (self.space, subject, key.strip().lower()))
        return [Note.of(row) for row in rows]

    def subjects(self) -> list[str]:
        rows = self.store.rows("select distinct subject from memories where space = ? and deleted_at is null "
                               "order by subject", (self.space,))
        return [row["subject"] for row in rows]

    def freshness(self, note: Note, now: float | None = None) -> float:
        """1.0 for lasting kinds; otherwise halves every `half_life_days` since it happened or was last recalled."""
        if note.kind in LASTING:
            return 1.0
        now = self.clock() if now is None else now
        touched = max(note.happened_at, note.recalled_at or 0.0)
        days = max(0.0, now - touched) / 86400
        return 0.5 ** (days / self.half_life_days)

    def recall(self, subject: str, query: str, *, limit: int = 6, budget: int = 800, important: int = 2,
               recent: int = 1, log: bool = True) -> Recall:
        """The notes worth bringing up for `query`: pinned ones, then the best evidence, then fillers.

        `budget` caps the characters of note text chosen. When there is room left, `important` adds that many
        lasting notes of importance 4+ that did not match (word search misses "my cat" against "年糕"), and
        `recent` that many of the newest episodes, so a fresh conversation has something to go on.
        """
        now = self.clock()
        live = self._live_where(subject)
        query_terms = texts.terms(query)
        note_terms = {note.id: set(texts.terms(note.text + " " + (note.key or "").replace(".", " "))) for note in live}
        count = len(live)
        weights = {}
        for term in query_terms:
            df = sum(1 for terms in note_terms.values() if term in terms)
            if df and (count < 8 or df <= count / 2):  # a term in half the notes says nothing
                weights[term] = math.log((count + 1) / (df + 0.5))
        scored: list[tuple[float, Note, tuple[str, ...]]] = []
        for note in live:
            matched = tuple(term for term in weights if term in note_terms[note.id])
            evidence = sum(weights[term] for term in matched)
            if evidence <= 0:
                continue
            fresh = self.freshness(note, now)
            score = (evidence * (0.25 + 0.75 * fresh) * (0.4 + 0.15 * note.importance)
                     * (1 + 0.3 * abs(note.feeling)))
            scored.append((score, note, matched))
        scored.sort(key=lambda item: (-item[0], -item[1].id))
        chosen: list[Recalled] = []
        skipped: list[tuple[Note, str]] = []
        used = 0

        def take(item: Recalled) -> bool:
            nonlocal used
            if len(chosen) >= limit:
                skipped.append((item.note, f"over the limit of {limit} notes"))
                return False
            if used + len(item.note.text) > budget and chosen:
                skipped.append((item.note, f"over the {budget}-character budget"))
                return False
            chosen.append(item)
            used += len(item.note.text)
            return True

        pinned = [note for note in live if note.importance >= PINNED]
        for note in sorted(pinned, key=lambda n: -n.id):
            take(Recalled(note, 0.0, "pinned"))
        taken = {item.note.id for item in chosen}
        for score, note, matched in scored:
            if note.id not in taken:
                take(Recalled(note, score, "matched: " + ", ".join(matched[:4]), matched))
        def fill(candidates: list[Note], count: int, why: str) -> None:
            nonlocal used
            for note in candidates:
                if count <= 0 or len(chosen) >= limit:
                    return
                if note.id in {item.note.id for item in chosen} or used + len(note.text) > budget:
                    continue
                chosen.append(Recalled(note, 0.0, why))
                used += len(note.text)
                count -= 1

        fill(sorted((note for note in live if note.kind in LASTING and note.importance >= 4),
                    key=lambda note: (-note.importance, -note.id)), important, "important")
        fill([note for note in live if note.kind not in LASTING], recent, "recent")  # live is newest first
        taken = {item.note.id for item in chosen}
        missed = [note for note in live if note.id not in taken and note.id not in {n.id for n, _ in skipped}]
        skipped += [(note, "nothing in common with the query") for note in missed[:5]]
        result = Recall(query, chosen, skipped[:10])
        if log and chosen:
            self._log(subject, result, now)
        return result

    def context(self, subject: str, query: str = "", *, name: str | None = None, limit: int = 6,
                budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None) -> str:
        """A block ready for a system prompt: the profile card, then the recalled notes with human dates.

        Returns "" when there is nothing to say, so callers can always append it.
        """
        found = self.recall(subject, query, limit=limit, budget=budget, important=important, recent=recent)
        card = self.profile(subject)
        if not found.chosen and not card:
            return ""
        now = self.clock()
        zh = self.lang == "zh"
        who = name or subject
        lines = [header or (f"你记得的关于{who}的事（日期是相对今天说的）：" if zh else
                            f"What you remember about {who} (dates are relative to today):")]
        if card:
            lines.append(("印象：" if zh else "Impression: ") + card)
        for item in found.chosen:
            note = item.note
            if note.kind in LASTING:
                lines.append(f"- {note.text}")
            else:
                lines.append(f"- [{dates.when(note.happened_at, now, self.zone, self.lang)}] {note.text}")
        return "\n".join(lines)

    # ---- profile card ------------------------------------------------------------------------------
    def profile(self, subject: str) -> str | None:
        row = self.store.row("select text from profiles where space = ? and subject = ?", (self.space, subject))
        return row["text"] if row else None

    def set_profile(self, subject: str, text: str | None) -> None:
        """A short standing impression of the subject (a few sentences), shown above the notes."""
        if not text:
            self.store.execute("delete from profiles where space = ? and subject = ?", (self.space, subject))
            return
        self.store.execute("insert into profiles (space, subject, text, updated_at) values (?, ?, ?, ?) on conflict"
                           "(space, subject) do update set text = excluded.text, updated_at = excluded.updated_at",
                           (self.space, subject, texts.clip(text, 1200), self.clock()))

    def recalls(self, subject: str, limit: int = 20) -> list[dict]:
        """The most recent recalls of a subject, newest first: what was asked, chosen and skipped."""
        rows = self.store.rows("select * from recalls where space = ? and subject = ? order by id desc limit ?",
                               (self.space, subject, limit))
        return [{"at": row["at"], "query": row["query"], "chosen": json.loads(row["chosen"]),
                 "skipped": json.loads(row["skipped"])} for row in rows]

    # ---- inside --------------------------------------------------------------------------------------
    def _live_where(self, subject: str, extra: str = "", parameters: tuple = ()) -> list[Note]:
        sql = ("select * from memories where space = ? and subject = ? and deleted_at is null and superseded_by is "
               "null" + (f" and {extra}" if extra else "") + " order by id desc")
        return [Note.of(row) for row in self.store.rows(sql, (self.space, subject) + tuple(parameters))]

    def _auto_today(self, subject: str, now: float) -> int:
        today = dates.local(now, self.zone).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        row = self.store.row("select count(*) as n from memories where space = ? and subject = ? and source = 'auto'"
                             " and created_at >= ?", (self.space, subject, today))
        return row["n"]

    def _prune(self, subject: str, now: float) -> None:
        live = self._live_where(subject)
        if len(live) <= self.max_notes:
            return
        fading = [note for note in live if note.kind not in LASTING and note.importance < PINNED]
        fading.sort(key=lambda note: note.importance * (0.25 + 0.75 * self.freshness(note, now)))
        for note in fading[:len(live) - self.max_notes]:
            self.store.execute("update memories set deleted_at = ?, source = coalesce(source, '') || ' pruned' "
                               "where id = ?", (now, note.id))

    def _log(self, subject: str, result: Recall, now: float) -> None:
        ids = [item.note.id for item in result.chosen if item.why.startswith("matched")]
        self.store.execute("insert into recalls (space, subject, at, query, chosen, skipped) values (?, ?, ?, ?, ?, ?)",
                           (self.space, subject, now, texts.clip(result.query, 300),
                            dumps([[item.note.id, item.why] for item in result.chosen]),
                            dumps([[note.id, reason] for note, reason in result.skipped])))
        if ids:
            self.store.execute(f"update memories set recalled_at = ?, recalls = recalls + 1 where id in "
                               f"({', '.join('?' * len(ids))})", (now, *ids))
        self.store.execute("delete from recalls where space = ? and subject = ? and id not in (select id from recalls"
                           " where space = ? and subject = ? order by id desc limit 200)",
                           (self.space, subject, self.space, subject))
