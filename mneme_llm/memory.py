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
from .meaning import Found, ledger
from .store import Store, dumps

KINDS = ("fact", "preference", "episode", "plan", "reflection")
LASTING = frozenset({"fact", "preference"})
KEY = re.compile(r"^[\w㐀-鿿]+(\.[\w㐀-鿿]+){0,3}$")
MAX_KEY = 48
MAX_TEXT = 500
MAX_PROFILE = 1200
PINNED = 5  # importance at which a note is always in context
SEMANTIC_WEIGHT = 4.0  # a close match in meaning counts about as much as one rare shared word
KEY_RULE = ("a key names what the note is about, like 'user.city' or 'cat.name' (no spaces, at most 4 parts and 48 "
            "characters); the value goes in the text")


def normal_key(key) -> str | None:
    """A key as it is stored: stripped and lowercase (None for no key)."""
    return key.strip().lower() or None if isinstance(key, str) else None


def note_fields(text, *, kind=None, key=None, importance=2, feeling=0.0, happened_at=None, gloss=None,
                strict: bool = True) -> dict | None:
    """A note's fields held to the rules of writing: one clean line of text, a known kind, a key that names a
    topic, importance 1-5, feeling -1..1, a time in seconds. Strict (a host's or a model's call): a wrong value
    raises ValueError or TypeError. Lenient (an import, the note writer's items): a wrong value is dropped or
    replaced by the default, and None comes back only when there is no text to keep."""
    def wrong(error: Exception, fallback):
        if strict:
            raise error
        return fallback
    if not isinstance(text, str):
        return wrong(TypeError(f"a memory's text must be a string, not {type(text).__name__}"), None)
    text = texts.clip(text, MAX_TEXT)
    if texts.blank(text):
        return wrong(ValueError("a memory needs some text"), None)
    if kind is not None and kind not in KINDS:
        kind = wrong(ValueError(f"kind must be one of {', '.join(KINDS)}"), None)
    if key is not None and not isinstance(key, str):
        key = wrong(ValueError("a key is text, like 'user.city'"), None)
    key = normal_key(key)
    if key is not None and (len(key) > MAX_KEY or not KEY.match(key)):
        key = wrong(ValueError(KEY_RULE), None)
    if gloss is not None and not isinstance(gloss, str):
        gloss = wrong(ValueError("a gloss is text"), None)
    gloss = (texts.clip(gloss, MAX_TEXT) or None) if gloss else None
    try:
        importance = max(1, min(5, int(importance)))
    except OverflowError:  # an integer too large for a float, or an infinity
        importance = 5 if importance > 0 else 1
    except (TypeError, ValueError):
        importance = wrong(ValueError("importance is a whole number from 1 to 5"), 2)
    try:
        feeling = float(feeling)
    except (TypeError, ValueError, OverflowError):
        feeling = wrong(ValueError("feeling is a number from -1 to 1"), 0.0)
    feeling = max(-1.0, min(1.0, feeling)) if math.isfinite(feeling) else 0.0
    if happened_at is not None and dates.seconds(happened_at) is None:
        happened_at = wrong(ValueError("happened_at is a time in seconds, between 1970 and the year 3000"), None)
    return {"text": text, "kind": kind, "key": key, "importance": importance, "feeling": feeling,
            "happened_at": None if happened_at is None else float(happened_at), "gloss": gloss}


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

    # ---- writing ---------------------------------------------------------------------------------
    def remember(self, subject: str, text: str, **options) -> Note | None:
        """Keep a note; returns it (or the existing note it repeats), or None when an automatic note is over quota.

        `source="auto"` marks notes a model chose to keep without being asked; at most `daily_quota` of those per
        subject per day are kept unless they are important (4+). Anything else (the person asked, an import)
        always lands.
        """
        return self.keep(subject, text, **options)[1]

    def keep(self, subject: str, text: str, *, kind: str | None = None, key: str | None = None,
             importance: int = 2, feeling: float = 0.0, happened_at: float | None = None,
             source: str | None = None, gloss: str | None = None) -> tuple[str, Note | None]:
        """`remember`, also saying what happened: "kept", "replaced" (a key's older note), "known" (the same
        text was already there) or "over quota". `gloss` is the note in the unifying language, if known. `kind`
        is "episode" when not given (and a note taking over a key keeps its own)."""
        texts.required(subject, "subject")
        fields = note_fields(text, kind=kind, key=key, importance=importance, feeling=feeling,
                             happened_at=happened_at, gloss=gloss)
        now = self.clock()
        with self.store.transaction():
            same = self._same_text(subject, fields["text"])
            if fields["key"] is not None:
                # Under a key, only a note with that key or with none is the same note (a keyless one may take the
                # key over); a note under another key is a different fact that happens to read the same.
                same = [note for note in same if note.key in (None, fields["key"])]
            if same:
                return self._merge(subject, next((note for note in same if note.key == fields["key"]), same[0]),
                                   fields)
            if source == "auto" and fields["importance"] < 4 and self._auto_today(subject, now) >= self.daily_quota:
                return "over quota", None
            new = self._insert(subject, {**fields, "kind": fields["kind"] or "episode",
                                         "happened_at": now if fields["happened_at"] is None else fields["happened_at"],
                                         "created_at": now,
                                         "source": source})
            replaced = self._supersede(subject, fields["key"], new) if fields["key"] is not None else 0
            self._prune(subject, now, keep=new)
        return ("replaced" if replaced else "kept"), self.get(new)

    def _merge(self, subject: str, note: Note, fields: dict) -> tuple[str, Note | None]:
        """The same words are already kept: the note keeps the higher importance and gains a gloss; under a key it
        did not have, it takes the key, the kind it is now given (and its day and feeling, when given), and
        replaces the key's older value."""
        self.store.execute("update memories set importance = max(importance, ?), gloss = coalesce(gloss, ?), terms ="
                           " case when gloss is null and ? is not null then null else terms end where id = ?",
                           (fields["importance"], fields["gloss"], fields["gloss"], note.id))
        if fields["key"] is None or note.key == fields["key"]:
            return "known", self.get(note.id)
        self.store.execute("update memories set key = ?, kind = ?, happened_at = ?, feeling = ?, terms = null where "
                           "id = ?", (fields["key"], fields["kind"] or note.kind,
                                      note.happened_at if fields["happened_at"] is None else fields["happened_at"],
                                      fields["feeling"] or note.feeling, note.id))
        replaced = self._supersede(subject, fields["key"], note.id)
        return ("replaced" if replaced else "kept"), self.get(note.id)

    def _insert(self, subject: str, row: dict) -> int:
        """A new note's row, with its case-folded text; vectors left under a reused id are dropped first."""
        row = {**row, "space": self.space, "subject": subject, "folded": texts.fold(row["text"])}
        new = self.store.execute(f"insert into memories ({', '.join(row)}) values ({', '.join('?' * len(row))})",
                                 tuple(row.values())).lastrowid
        ledger.unteach(self.store, [new])  # SQLite reuses the id of a deleted note; nothing of it may stay
        return new

    def _supersede(self, subject: str, key: str, by: int) -> int:
        """Point the key's other live notes to `by`, its value now; returns how many it replaced."""
        return self.store.execute("update memories set superseded_by = ? where space = ? and subject = ? and key = ?"
                                  " and id != ? and superseded_by is null and deleted_at is null",
                                  (by, self.space, subject, key, by)).rowcount

    def forget(self, subject: str, *, id: int | None = None, key: str | None = None) -> int:
        """Remove a note (by id) or the live note of a key; returns how many were removed. History stays on disk
        (soft delete) until `purge`."""
        if (id is None) == (key is None):
            raise ValueError("forget takes exactly one of id or key")
        where, value = ("id = ?", id) if id is not None else ("key = ?", normal_key(key))
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
            ledger.unteach(self.store, [row["id"] for row in self.store.rows(
                sql.replace("delete from", "select id from", 1), parameters)])
            count = self.store.execute(sql, parameters).rowcount
        return count

    def erase(self, subject: str) -> int:
        """Every note about a subject gone for good, with their history, vectors, profile card and recall log;
        what the notes taught the word centroids is taken back, so none of their words stay. (`Mneme.erase` also
        resets the mood, for "forget me".)"""
        with self.store.transaction():
            ledger.unteach(self.store, [row["id"] for row in self.store.rows(
                "select id from memories where space = ? and subject = ?", (self.space, subject))])
            count = self.store.execute("delete from memories where space = ? and subject = ?",
                                       (self.space, subject)).rowcount
            for table in ("recalls", "profiles"):
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
        """Every version a key has had, oldest first (the last is live unless it was forgotten; an older note that
        took the key over comes after the ones it replaced)."""
        notes = [Note.of(row) for row in self.store.rows("select * from memories where space = ? and subject = ? and "
                                                          "key = ? order by id", (self.space, subject,
                                                                                  normal_key(key)))]
        successor = {note.id: note.superseded_by for note in notes}

        def ahead(note: Note) -> int:  # how many replacements came after it
            steps, at, seen = 0, note.id, set()
            while successor.get(at) in successor and at not in seen:
                seen.add(at)
                at, steps = successor[at], steps + 1
            return steps
        return sorted(notes, key=lambda note: (-ahead(note), note.id))

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
        return self._rank(subject, self._query(query), self._live_where(subject), Found(), limit, budget, important,
                          recent, log)

    async def arecall(self, subject: str, query: str, *, limit: int = 6, budget: int = 800, important: int = 2,
                      recent: int = 1, log: bool = True, complete=None) -> Recall:
        """`recall` with the meaning tiers: notes close in meaning count as evidence too, in any language.
        `complete` gives the unify tier a chat model for this call."""
        query = self._query(query)
        live = self._live_where(subject)
        if self.meaning is None or not query.strip() or not live:
            return self._rank(subject, query, live, Found(), limit, budget, important, recent, log)
        found = await self.meaning.find(live, query, complete=complete)
        if found.glosses:
            self._write_glosses(found.glosses)
            live = self._live_where(subject)
        return self._rank(subject, query, live, found, limit, budget, important, recent, log)

    def context(self, subject: str, query: str = "", *, user: str | None = None, limit: int = 6,
                budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None) -> str:
        """A block ready for a system prompt: a header saying these are data and not instructions, the profile
        card, then the recalled notes with human dates (each note is one line, so none can pose as a header).

        `user` is how the header names the person (their id otherwise). Returns "" when there is nothing to say,
        so callers can always append it.
        """
        found = self.recall(subject, query, limit=limit, budget=budget, important=important, recent=recent)
        return self._render(subject, found, user, header)

    async def acontext(self, subject: str, query: str = "", *, user: str | None = None, limit: int = 6,
                       budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None,
                       complete=None) -> str:
        """`context` with the meaning tiers (see `arecall`)."""
        found = await self.arecall(subject, query, limit=limit, budget=budget, important=important, recent=recent,
                                   complete=complete)
        return self._render(subject, found, user, header)

    def _render(self, subject: str, found: Recall, user: str | None, header: str | None) -> str:
        card = self.profile(subject)
        if not found.chosen and not card:
            return ""
        now = self.clock()
        lines = [header or say(self.lang, "notes.header", who=user or subject)]
        if card:
            lines.append(say(self.lang, "notes.impression") + texts.clip(card, MAX_PROFILE))
        for item in found.chosen:
            note = item.note
            if note.kind in LASTING:
                lines.append(f"- {note.text}")
            else:
                lines.append(f"- [{dates.when(note.happened_at, now, self.zone, self.lang)}] {note.text}")
        return "\n".join(lines)

    def _rank(self, subject: str, query: str, live: list[Note], found: Found, limit: int, budget: int,
              important: int, recent: int, log: bool) -> Recall:
        now = self.clock()
        scored = self._score(live, texts.terms(query + (" " + found.words if found.words else "")), found, now)
        chosen, skipped = self._choose(live, scored, limit, budget, important, recent)
        result = Recall(query, chosen, skipped[:10], found.tier)
        if log and chosen:
            self._log(subject, result, now)
        return result

    def _score(self, live: list[Note], query_terms: list[str], found: Found, now: float) -> list:
        """Every note with any evidence for the query, best first: rare shared terms (and closeness in meaning,
        above the tier's floor), times freshness, importance and feeling."""
        note_terms = self._terms(live)
        count = len(live)
        weights = {}
        for term in query_terms:
            df = sum(1 for terms in note_terms.values() if term in terms)
            if df and (count < 8 or df <= count / 2):  # a term in half the notes says nothing
                weights[term] = math.log((count + 1) / (df + 0.5))
        scored: list[tuple[float, Note, tuple[str, ...], str]] = []
        for note in live:
            matched = tuple(term for term in weights if term in note_terms[note.id])
            evidence = sum(weights[term] for term in matched)
            similar = found.similarities.get(note.id)
            closeness = max(0.0, (similar - found.floor) / (1 - found.floor)) if similar is not None else 0.0
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
        return scored

    def _choose(self, live: list[Note], scored: list, limit: int, budget: int, important: int,
                recent: int) -> tuple[list[Recalled], list[tuple[Note, str]]]:
        """Within `limit` notes and `budget` characters: pinned notes, then the best evidence, then fillers (the
        important lasting notes and the newest episodes); and why the closest others were left out."""
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
        passed = {note.id for note, _ in skipped}
        missed = [note for note in live if note.id not in taken and note.id not in passed]
        skipped += [(note, "nothing in common with the query") for note in missed[:5]]
        return chosen, skipped

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
        texts.required(subject, "subject")
        if text is not None and not isinstance(text, str):
            raise TypeError(f"a profile must be a string, not {type(text).__name__}")
        self._put_profile(subject, text, self.clock())

    def _put_profile(self, subject: str, text: str | None, at: float) -> None:
        if not text or texts.blank(texts.clip(text, MAX_PROFILE)):
            self.store.execute("delete from profiles where space = ? and subject = ?", (self.space, subject))
            return
        self.store.execute("insert into profiles (space, subject, text, updated_at) values (?, ?, ?, ?) on conflict"
                           "(space, subject) do update set text = excluded.text, updated_at = excluded.updated_at",
                           (self.space, subject, texts.clip(text, MAX_PROFILE), at))

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
                    # Only if the note is still as it was read: another writer may have set its gloss or key since.
                    self.store.execute("update memories set terms = ? where id = ? and terms is null and key is ? and "
                                       "gloss is ?", (" ".join(terms), note.id, note.key, note.gloss))
        return found

    # ---- moving between files ----------------------------------------------------------------------
    def export_rows(self) -> dict:
        """This space's notes and profile cards as plain rows (without the caches: terms and folded text)."""
        memories = [{key: value for key, value in dict(row).items() if key not in ("terms", "folded")}
                    for row in self.store.rows("select * from memories where space = ? order by id", (self.space,))]
        profiles = [dict(row) for row in self.store.rows("select * from profiles where space = ? order by rowid",
                                                          (self.space,))]
        return {"memories": memories, "profiles": profiles}

    def import_rows(self, memories, profiles=()) -> int:
        """Add exported notes and profile cards to this space, held to the rules of writing (`clean`): ids are
        renumbered and links between notes follow; then each subject keeps one live note per key (the newest)
        and no live text twice. Returns how many notes were added."""
        renumbered, links, subjects, added, now = {}, [], set(), 0, self.clock()
        with self.store.transaction():
            for original in memories:
                row = self.clean(original) if isinstance(original, dict) else None
                if row is None:
                    continue
                new = self._insert(row.pop("subject"), row)
                subjects.add(original["subject"])
                added += 1
                if isinstance(original.get("id"), (int, str)):
                    renumbered[original["id"]] = new
                if original.get("superseded_by") is not None:  # one that is no id points nowhere
                    successor = original["superseded_by"]
                    links.append((new, successor if isinstance(successor, (int, str)) else None))
            for new, successor in links:  # a link to a note that did not come along becomes "replaced" (-1)
                self.store.execute("update memories set superseded_by = ? where id = ?",
                                   (renumbered.get(successor, -1), new))
            for subject in subjects:
                self._settle(subject, now)
            for row in profiles:
                if isinstance(row, dict) and isinstance(row.get("subject"), str) and row["subject"].strip() and \
                        isinstance(row.get("text"), str):
                    at = dates.seconds(row.get("updated_at"))
                    self._put_profile(row["subject"], row["text"], now if at is None else at)
        return added

    @staticmethod
    def clean(row: dict) -> dict | None:
        """An exported note held to the rules of writing (`note_fields`, lenient), with its subject and the
        columns an export carries (times in seconds, counts, source); None when there is no text or subject."""
        subject = row.get("subject")
        fields = note_fields(row.get("text"), kind=row.get("kind"), key=row.get("key"),
                             importance=row.get("importance", 2), feeling=row.get("feeling", 0.0),
                             happened_at=row.get("happened_at"), gloss=row.get("gloss"), strict=False)
        if fields is None or not isinstance(subject, str) or not subject.strip():
            return None
        created = dates.seconds(row.get("created_at"))
        created = time.time() if created is None else created
        try:
            recalls = max(0, min(2 ** 31, int(row.get("recalls") or 0)))
        except (TypeError, ValueError, OverflowError):
            recalls = 0

        def moment(name):  # an optional time: kept when it is one, the note's own when not, absent when absent
            found = dates.seconds(row.get(name))
            return None if row.get(name) is None else created if found is None else found
        return {**fields, "subject": subject, "kind": fields["kind"] or "episode",
                "happened_at": created if fields["happened_at"] is None else fields["happened_at"],
                "created_at": created, "recalls": recalls,
                "recalled_at": moment("recalled_at"), "deleted_at": moment("deleted_at"),
                "source": row.get("source") if isinstance(row.get("source"), str) else None}

    def _settle(self, subject: str, now: float) -> None:
        """After an import, the rules writing keeps: one live note per key (the newest wins, the others become its
        history) and no live text twice (a copy with a key is kept over one without, then the oldest)."""
        self._fill_folded(subject)
        rows = self.store.rows("select id, key, folded from memories where space = ? and subject = ? and deleted_at "
                               "is null and superseded_by is null order by created_at, id", (self.space, subject))
        newest = {row["key"]: row["id"] for row in rows if row["key"] is not None}
        for key, by in newest.items():
            self._supersede(subject, key, by)
        groups: dict[str, list] = {}
        for row in rows:
            if row["key"] is None or newest[row["key"]] == row["id"]:
                groups.setdefault(row["folded"], []).append(row)
        for group in groups.values():
            keep = {row["id"] for row in group if row["key"] is not None} or {group[0]["id"]}
            for row in group:
                if row["id"] not in keep:
                    self.store.execute("update memories set deleted_at = ?, source = coalesce(source, '') || "
                                       "' duplicate' where id = ?", (now, row["id"]))

    def _write_glosses(self, glosses: dict[int, str]) -> None:
        """Glosses the unify tier wrote, kept unless the note got one meanwhile; its cached terms then change."""
        with self.store.transaction():
            for id, gloss in glosses.items():
                self.store.execute("update memories set gloss = ?, terms = null where id = ? and gloss is null",
                                   (texts.clip(gloss, MAX_TEXT) or None, id))

    @staticmethod
    def _query(query) -> str:
        if not isinstance(query, str):
            raise TypeError(f"a query must be a string, not {type(query).__name__}")
        return texts.clean(query)

    def _same_text(self, subject: str, text: str) -> list[Note]:
        """Live notes with the same words, whatever the letters' case in any alphabet ("Straße" is "STRASSE"): by
        the case-folded text kept beside each note."""
        self._fill_folded(subject)
        return self._live_where(subject, "folded = ?", (texts.fold(text),))

    def _fill_folded(self, subject: str) -> None:
        """The case-folded text of notes written before it was kept beside them; any comparison of texts needs it."""
        for row in self.store.rows("select id, text from memories where space = ? and subject = ? and folded is null",
                                   (self.space, subject)):
            self.store.execute("update memories set folded = ? where id = ?", (texts.fold(row["text"]), row["id"]))

    def _live_where(self, subject: str, extra: str = "", parameters: tuple = ()) -> list[Note]:
        sql = ("select * from memories where space = ? and subject = ? and deleted_at is null and superseded_by is "
               "null" + (f" and {extra}" if extra else "") + " order by id desc")
        return [Note.of(row) for row in self.store.rows(sql, (self.space, subject) + tuple(parameters))]

    def _auto_today(self, subject: str, now: float) -> int:
        today = dates.local(now, self.zone).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        row = self.store.row("select count(*) as n from memories where space = ? and subject = ? and source = 'auto'"
                             " and created_at >= ?", (self.space, subject, today))
        return row["n"]

    def _prune(self, subject: str, now: float, keep: int | None = None) -> None:
        count = self.store.row("select count(*) as n from memories where space = ? and subject = ? and deleted_at is "
                               "null and superseded_by is null", (self.space, subject))["n"]
        if count <= self.max_notes:
            return
        live = self._live_where(subject)
        fading = [note for note in live if note.kind not in LASTING and note.importance < PINNED and note.id != keep]
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
