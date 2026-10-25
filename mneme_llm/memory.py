"""Memories about people: written as short notes, recalled by evidence, rendered with human dates.

A note is one sentence about a subject ("Has a cat named 年糕"). Kinds say how it ages:

    fact, preference    lasting; never fade ("lives in Shanghai", "hates coriander")
    episode, plan       fade with a half-life (30 days by default) unless recalled again
    reflection          the companion's own impression; fades like an episode

A `key` ("user.city", "cat.name": what the note is about, never its value) makes a newer note replace the older
one, and the old version stays in the history. Recall scores each note by evidence (query terms it shares,
weighted by how rare they are among this person's notes, plus, with `arecall`, how close it is in meaning) times
freshness, importance and feeling, then fills a small budget; every recall can explain what was chosen and what
was skipped and why. Notes are rendered as data, never as instructions (see `context`).
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
from .i18n import say
from .meaning import cosine
from .store import Store, dumps

KINDS = ("fact", "preference", "episode", "plan", "reflection")
LASTING = frozenset({"fact", "preference"})
KEY = re.compile(r"^[\w㐀-鿿]+(\.[\w㐀-鿿]+){0,3}$")
MAX_KEY = 48
MAX_TEXT = 500
PINNED = 5  # importance at which a note is always in context
SEMANTIC_WEIGHT = 4.0  # a close match in meaning counts about as much as one rare shared word
# Similarity below the floor says nothing. Measured for text-embedding-3-small (256 dimensions) on English and
# Chinese notes: related pairs 0.30-0.60 (mean 0.45), unrelated ones mean 0.18 with 95% under 0.34. Micro
# centroids are averages, so they sit closer together and get a higher floor. `Memory.floors` overrides these.
FLOORS = {"embeddings": 0.33, "micro": 0.45}


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
    gloss: str | None = None  # the note in the unifying language, when the unify tier wrote one

    @classmethod
    def of(cls, row) -> "Note":
        return cls(row["id"], row["subject"], row["text"], row["kind"], row["key"], row["importance"], row["feeling"],
                   row["happened_at"], row["created_at"], row["recalls"], row["source"], row["recalled_at"],
                   row["superseded_by"], row["deleted_at"], row["gloss"])

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "kind": self.kind, "key": self.key, "importance": self.importance,
                "feeling": self.feeling, "happened_at": self.happened_at, "created_at": self.created_at}


@dataclass(frozen=True)
class Recalled:
    note: Note
    score: float
    why: str                      # "pinned", "matched: 考试, 复习", "similar 0.62", "important" or "recent"
    matched: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recall:
    query: str
    chosen: list[Recalled]
    skipped: list[tuple[Note, str]] = field(default_factory=list)  # (note, reason) for the closest misses
    tier: str = ""  # which meaning tier helped ("embeddings", "micro", "unify"), "" for words alone

    def explain(self) -> str:
        lines = [f"recall for {self.query!r}" + (f" (meaning: {self.tier})" if self.tier else "") + ":"]
        lines += [f"  + #{r.note.id} {r.why} (score {r.score:.2f}): {texts.clip(r.note.text, 70)}" for r in self.chosen]
        lines += [f"  - #{note.id} {reason}: {texts.clip(note.text, 70)}" for note, reason in self.skipped]
        return "\n".join(lines)


class Memory:
    """The notes of one space. Every method takes the subject the note is about."""

    def __init__(self, store: Store, space: str, *, half_life_days: float = 30.0, daily_quota: int = 8,
                 max_notes: int = 5000, zone: tzinfo | None = None, lang: str = "en", meaning=None,
                 clock: Callable[[], float] = time.time):
        self.store, self.space = store, space
        self.half_life_days, self.daily_quota, self.max_notes = half_life_days, daily_quota, max_notes
        self.zone, self.lang, self.meaning, self.clock = zone, lang, meaning, clock
        self.floors = dict(FLOORS)

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
             source: str | None = None, gloss: str | None = None) -> tuple[str, Note | None]:
        """`remember`, also saying what happened: "kept", "replaced" (a key's older note), "known" (the same
        text was already there) or "over quota". `gloss` is the note in the unifying language, if known."""
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
        gloss = texts.clip(gloss, MAX_TEXT) if gloss else None
        with self.store.transaction():
            same = self._live_where(subject, "lower(text) = lower(?)", (text,))
            if same:
                note = same[0]
                self.store.execute("update memories set importance = max(importance, ?), gloss = coalesce(gloss, ?),"
                                   " terms = case when gloss is null and ? is not null then null else terms end "
                                   "where id = ?", (importance, gloss, gloss, note.id))
                return "known", self.get(note.id)
            if source == "auto" and importance < 4 and self._auto_today(subject, now) >= self.daily_quota:
                return "over quota", None
            cursor = self.store.execute(
                "insert into memories (space, subject, key, kind, text, importance, feeling, happened_at, created_at,"
                " source, gloss) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.space, subject, key, kind, text, importance, feeling, happened_at, now, source, gloss))
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
        with self.store.transaction():
            count = self.store.execute(sql, parameters).rowcount
            self._drop_orphans()
        return count

    def erase(self, subject: str) -> int:
        """Everything about a subject, gone: notes, history, profile, mood (for "forget me")."""
        with self.store.transaction():
            count = self.store.execute("delete from memories where space = ? and subject = ?",
                                       (self.space, subject)).rowcount
            for table in ("recalls", "profiles", "moods", "mood_events"):
                self.store.execute(f"delete from {table} where space = ? and subject = ?", (self.space, subject))
            self._drop_orphans()
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

        Word matching only, with no network (glosses the unify tier wrote earlier count as words); `arecall`
        adds the meaning tiers. `budget` caps the characters of note text chosen. When there is room left,
        `important` adds that many lasting notes of importance 4+ that did not match, and `recent` that many of
        the newest episodes, so a fresh conversation has something to go on.
        """
        return self._rank(subject, query, self._live_where(subject), {}, "", "", limit, budget, important, recent,
                          log)

    async def arecall(self, subject: str, query: str, *, limit: int = 6, budget: int = 800, important: int = 2,
                      recent: int = 1, log: bool = True, complete=None) -> Recall:
        """`recall` with the meaning tiers: notes close in meaning count as evidence too, in any language.
        `complete` gives the unify tier a chat model for this call."""
        live = self._live_where(subject)
        if self.meaning is None or not query.strip() or not live:
            return self._rank(subject, query, live, {}, "", "", limit, budget, important, recent, log)
        await self.meaning.prepare_vectors(live)
        found = await self.meaning.query(query, complete=complete)
        similarities = {}
        if found.vector is not None:
            similarities = {id: cosine(found.vector, vector)
                            for id, vector in self.meaning.vectors([note.id for note in live]).items()}
        elif self.meaning.unify is not None and await self.meaning.prepare_glosses(live, complete=complete):
            live = self._live_where(subject)  # with the glosses just written
        return self._rank(subject, query, live, similarities, found.tier, found.words, limit, budget, important,
                          recent, log)

    def context(self, subject: str, query: str = "", *, name: str | None = None, limit: int = 6,
                budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None) -> str:
        """A block ready for a system prompt: a header saying these are data and not instructions, the profile
        card, then the recalled notes with human dates (each note is one line, so none can pose as a header).

        Returns "" when there is nothing to say, so callers can always append it.
        """
        found = self.recall(subject, query, limit=limit, budget=budget, important=important, recent=recent)
        return self._render(subject, found, name, header)

    async def acontext(self, subject: str, query: str = "", *, name: str | None = None, limit: int = 6,
                       budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None,
                       complete=None) -> str:
        """`context` with the meaning tiers (see `arecall`)."""
        found = await self.arecall(subject, query, limit=limit, budget=budget, important=important, recent=recent,
                                   complete=complete)
        return self._render(subject, found, name, header)

    def _render(self, subject: str, found: Recall, name: str | None, header: str | None) -> str:
        card = self.profile(subject)
        if not found.chosen and not card:
            return ""
        now = self.clock()
        lines = [header or say(self.lang, "notes.header", who=name or subject)]
        if card:
            lines.append(say(self.lang, "notes.impression") + texts.clip(card, 1200))
        for item in found.chosen:
            note = item.note
            if note.kind in LASTING:
                lines.append(f"- {note.text}")
            else:
                lines.append(f"- [{dates.when(note.happened_at, now, self.zone, self.lang)}] {note.text}")
        return "\n".join(lines)

    def _rank(self, subject: str, query: str, live: list[Note], similarities: dict[int, float], tier: str,
              words: str, limit: int, budget: int, important: int, recent: int, log: bool) -> Recall:
        now = self.clock()
        query_terms = texts.terms(query + (" " + words if words else ""))
        note_terms = self._terms(live)
        count = len(live)
        weights = {}
        for term in query_terms:
            df = sum(1 for terms in note_terms.values() if term in terms)
            if df and (count < 8 or df <= count / 2):  # a term in half the notes says nothing
                weights[term] = math.log((count + 1) / (df + 0.5))
        floor = self.floors.get(tier, FLOORS["embeddings"])
        scored: list[tuple[float, Note, tuple[str, ...], str]] = []
        for note in live:
            matched = tuple(term for term in weights if term in note_terms[note.id])
            evidence = sum(weights[term] for term in matched)
            similar = similarities.get(note.id)
            closeness = max(0.0, (similar - floor) / (1 - floor)) if similar is not None else 0.0
            relevance = evidence + SEMANTIC_WEIGHT * closeness
            if relevance <= 0:
                continue
            fresh = self.freshness(note, now)
            score = (relevance * (0.25 + 0.75 * fresh) * (0.4 + 0.15 * note.importance)
                     * (1 + 0.3 * abs(note.feeling)))
            why = ", ".join(part for part in (
                "matched: " + ", ".join(matched[:4]) if matched else "",
                f"similar {similar:.2f}" if closeness > 0 else "") if part)
            scored.append((score, note, matched, why))
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
        for score, note, matched, why in scored:
            if note.id not in taken:
                take(Recalled(note, score, why, matched))

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
        result = Recall(query, chosen, skipped[:10], tier)
        if log and chosen:
            self._log(subject, result, now)
        return result

    # ---- profile card ------------------------------------------------------------------------------
    def profile(self, subject: str) -> str | None:
        row = self.store.row("select text from profiles where space = ? and subject = ?", (self.space, subject))
        return row["text"] if row else None

    def profile_updated_at(self, subject: str) -> float | None:
        """When the profile card was last written (None if there is none), so hosts can refresh it daily."""
        row = self.store.row("select updated_at from profiles where space = ? and subject = ?", (self.space, subject))
        return row["updated_at"] if row else None

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
    def _terms(self, notes: list[Note]) -> dict[int, set[str]]:
        """Each note's search terms (text, key and gloss), cached in the file and rebuilt when the tokenizer
        changes (turning jieba on, a new release)."""
        if self.store.meta("terms_version") != texts.version():
            with self.store.transaction():
                self.store.execute("update memories set terms = null")
                self.store.set_meta("terms_version", texts.version())
        found: dict[int, set[str]] = {}
        ids = [note.id for note in notes]
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            rows = self.store.rows(f"select id, terms from memories where id in ({', '.join('?' * len(chunk))})", chunk)
            found.update({row["id"]: set(row["terms"].split()) for row in rows if row["terms"] is not None})
        missing = [note for note in notes if note.id not in found]
        if missing:
            with self.store.transaction():
                for note in missing:
                    terms = texts.terms(" ".join([note.text, (note.key or "").replace(".", " "), note.gloss or ""]))
                    found[note.id] = set(terms)
                    self.store.execute("update memories set terms = ? where id = ?", (" ".join(terms), note.id))
        return found

    def _drop_orphans(self) -> None:
        self.store.execute("delete from vectors where memory_id not in (select id from memories)")

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
        ids = [item.note.id for item in result.chosen if item.why.startswith(("matched", "similar"))]
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
