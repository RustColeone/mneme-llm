"""Episodes: what was said, kept word for word, found again when it matters, fading the way people forget.

A note (`memory.py`) is what the companion made of a conversation; an episode is the conversation itself: one
exchange (the person's message and the reply, each line with who said it), when it was said and in which
conversation. Every exchange the person starts is kept, so nothing said is lost to a note writer that left it out
(on LoCoMo the words beat the notes by 16 to 22 points; docs/DESIGN.md, "Episodes").

They come back two ways:

    look     what comes to mind unprompted, for the message at hand: the best matches within a budget of
             characters, shown in the order they were said. Here a faded exchange counts less.
    search   what the model looks for itself, with a tool (`tools.py`): by relevance alone, however faded, so an
             old thing asked about is still found; what it finds is rehearsed, and fades slower from then on.

Ranking is BM25 over the search terms (`text.terms`), fused by reciprocal rank with closeness in meaning (tier 1's
vectors); with no embedder, BM25 alone. Retention is R = e^(−t/S): t the time since the exchange was said or last
rehearsed, S its stability (`days`, 30 to start). A rehearsal multiplies S by 1.5 + 3·(1 − R), so a thing that comes
back just as it was fading lasts much longer, and it is fresh again. An exchange rehearses the earlier ones it is
about: its three nearest in meaning, when they are closer than 98% of the pairs of this person's exchanges.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import tzinfo
from typing import Callable, Iterable

from . import dates, exchange as exchanges, text as texts
from .decide import fit
from .i18n import Speaks, Words, say
from .meaning import cosine, pack, unpack
from .people import People, Resolves
from .store import Store, dumps

try:  # optional: compares a person's thousands of exchanges at once
    import numpy
except ImportError:  # (the library needs nothing but Python)
    numpy = None

DAY = 86400.0
FLOOR = 0.25          # what a faded exchange still counts in a look: found later, never lost
NEAREST = 3           # the earlier exchanges one exchange may rehearse
SPREAD = 0.98         # ... when closer than this share of the person's pairs
SPREAD_PAIRS = 100    # pairs seen before any exchange rehearses another
BINS = 200            # the spread's histogram: similarity from −1 to 1 in steps of 0.01
MAX_LINE = 8000       # characters of one line kept (its opening and its end, when longer)
MAX_LINES = 40        # lines of one exchange
MAX_NAME = 80         # characters of who said a line
SHOWN_LINE = 2000     # characters of one line shown to a model
RRF = 61              # reciprocal rank fusion: a ranking's place p counts 1 / (RRF + p)
BATCH = 64            # exchanges embedded per request
SCANNED = 200         # the best-ranked exchanges a look reads to fill its budget
STRONGEST = 1e6       # days: stability stops growing here


@dataclass(frozen=True)
class Episode:
    id: int
    subject: str
    at: float                       # when it was said
    conversation: str               # where: the host's name for the chat it was said in ("" for none)
    lines: tuple[tuple[str, str], ...]  # (who, said), in order
    stability: float                # S, in days
    recalled_at: float | None = None  # when it was last rehearsed
    recalls: int = 0

    @property
    def text(self) -> str:
        return exchanges.text_of(self.lines)

    @classmethod
    def of(cls, row) -> "Episode":
        lines = tuple((str(who), str(said)) for who, said in json.loads(row["lines"]))
        return cls(row["id"], row["subject"], row["at"], row["conversation"], lines, row["stability"],
                   row["recalled_at"], row["recalls"])


def lines_of(exchange) -> list[tuple[str, str]]:
    """An exchange's lines as they are kept: who said each (one line) and what (cleaned; the opening and the end of
    a very long one), empty ones left out, at most MAX_LINES."""
    kept = []
    for who, said in exchanges.as_lines(exchange):
        said = texts.clean(said).strip()
        if texts.blank(said):
            continue
        kept.append((texts.clip(who, MAX_NAME), fit(said, MAX_LINE)))
    return kept[:MAX_LINES]


def spread_bin(value: float) -> int:
    return max(0, min(BINS - 1, int((value + 1) / 2 * BINS)))


def threshold(bins: list[int], pairs: int, share: float = SPREAD) -> float | None:
    """The similarity a share of the pairs is under (the lower edge of its bin), or None with too few pairs."""
    if pairs < SPREAD_PAIRS:
        return None
    above, wanted = 0, max(1, math.ceil((1 - share) * pairs - 1e-9))
    for index in range(BINS - 1, -1, -1):
        above += bins[index]
        if above >= wanted:
            return -1 + 2 * index / BINS
    return -1.0


class _Matrix:
    """A person's exchange vectors from one embedder, kept in memory: read once, then only what was added."""

    def __init__(self):
        self.ids: list[int] = []
        self.ats: list[float] = []
        self.read = 0   # rows read, a vector of another length among them (it is not compared)
        self.last = 0   # the highest episode id read
        self._data = None
        self.count = 0

    def add(self, id: int, at: float, vector) -> None:
        self.read += 1
        self.last = max(self.last, id)
        if numpy is not None:
            if self._data is None:
                self._data = numpy.zeros((64, len(vector)), dtype=numpy.float32)
            elif len(vector) != self._data.shape[1]:
                return
            if self.count == len(self._data):
                self._data = numpy.concatenate([self._data, numpy.zeros_like(self._data)])
            self._data[self.count] = vector
        else:
            if self._data is None:
                self._data = []
            elif len(vector) != len(self._data[0]):
                return
            self._data.append(list(vector))
        self.ids.append(id)
        self.ats.append(at)
        self.count += 1

    def similarities(self, vector):
        """Cosine with each vector, in the order of `ids` (an array with numpy, else a list; empty when there are
        none of this length)."""
        if not self.count:
            return []
        if numpy is not None:
            if len(vector) != self._data.shape[1]:
                return []
            return self._data[:self.count] @ numpy.asarray(vector, dtype=numpy.float32)
        if len(vector) != len(self._data[0]):
            return []
        return [cosine(row, vector) for row in self._data]

    def order(self, similarities) -> list[int]:
        """Positions in `ids`, the closest first."""
        if numpy is not None and len(similarities):
            return numpy.argsort(-similarities, kind="stable").tolist()
        return sorted(range(len(similarities)), key=lambda index: -similarities[index])

    def nearest(self, similarities, before: float, line: float, count: int = NEAREST) -> list[int]:
        """The ids of the `count` closest exchanges said before `before`, those at least `line` close."""
        if not len(similarities):
            return []
        if numpy is not None:
            values = numpy.where(numpy.asarray(self.ats) < before, similarities, -numpy.inf)
            top = numpy.argpartition(-values, count)[:count] if len(values) > count else range(len(values))
            top = sorted(top, key=lambda index: -values[index])
            return [self.ids[index] for index in top if values[index] >= line]
        earlier = heapq.nlargest(count, ((value, id) for id, at, value in zip(self.ids, self.ats, similarities)
                                         if at < before))
        return [id for value, id in earlier if value >= line]


def tally(bins: list[int], similarities) -> int:
    """Count these similarities into the spread's histogram; returns how many pairs they were."""
    if not len(similarities):
        return 0
    if numpy is not None:
        places = numpy.clip(((numpy.asarray(similarities) + 1) / 2 * BINS).astype(int), 0, BINS - 1)
        bins[:] = [have + int(more) for have, more in zip(bins, numpy.bincount(places, minlength=BINS))]
    else:
        for value in similarities:
            bins[spread_bin(value)] += 1
    return len(similarities)


class Episodes(Speaks, Resolves):
    """The exchanges of one space, kept under the person each was with (or, with `people`, any subject the person
    goes by)."""

    LOOK_WAIT = 3.0  # seconds a look waits for its query's vector before it ranks by words alone

    def __init__(self, store: Store, space: str, *, days: float = 30.0, zone: tzinfo | None = None,
                 display_language: str | Words = "en", meaning=None, people: People | None = None,
                 clock: Callable[[], float] = time.time):
        self.store, self.space, self.days, self.people = store, space, days, people
        self.words = Words.of(display_language)
        self.zone, self.meaning, self.clock = zone, meaning, clock
        self._matrices: dict[tuple[str, str], _Matrix] = {}
        self._queries: OrderedDict[str, object] = OrderedDict()  # recent queries' vectors (a turn asks again)

    # ---- writing ---------------------------------------------------------------------------------
    def keep(self, subject: str, exchange, *, at: float | None = None, conversation: str = "") -> Episode | None:
        """Keep an exchange word for word (a string, or `(who, said)` pairs or chat messages); returns it, or None
        when it has no words. `at` is when it was said (now when not given); `conversation` is where (a chat, a
        channel: any name of the host's), so a look can leave out what the host still shows of it."""
        texts.required(subject, "subject")
        lines = lines_of(exchange)
        if not lines:
            return None
        when = self.clock() if at is None else dates.seconds(at)
        if when is None:
            raise ValueError("at is a time in seconds, between 1970 and the year 3000")
        if not isinstance(conversation, str):
            raise TypeError(f"a conversation is named by a string, not {type(conversation).__name__}")
        with self.writing(subject) as subject:
            id = self._insert(subject, {"at": when, "conversation": texts.clip(conversation, 200), "lines": lines,
                                        "stability": self.days, "recalled_at": None, "recalls": 0})
        return self.get(id)

    async def akeep(self, subject: str, exchange, **options) -> Episode | None:
        """`keep`, then its vector (meaning tier 1), with which it rehearses the earlier exchanges it is about."""
        episode = self.keep(subject, exchange, **options)
        if episode is not None:
            await self.prepare(episode.subject)
        return episode

    def _insert(self, subject: str, row: dict) -> int:
        terms = texts.terms(" ".join(f"{who} {said}" for who, said in row["lines"]))
        id = self.store.execute("insert into episodes (space, subject, at, conversation, lines, size, stability, "
                                "recalled_at, recalls, terms) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (self.space, subject, row["at"], row["conversation"], dumps(row["lines"]),
                                 len(terms), row["stability"], row["recalled_at"], row["recalls"],
                                 " ".join(terms))).lastrowid
        for table in ("episode_vectors", "episode_terms"):  # SQLite reuses a deleted row's id: nothing of it stays
            self.store.execute(f"delete from {table} where episode_id = ?", (id,))
        for term in terms:
            self.store.execute("insert or ignore into episode_terms (space, subject, term, episode_id) values "
                               "(?, ?, ?, ?)", (self.space, subject, term, id))
        return id

    async def prepare(self, subject: str, *, limit: int = 20_000) -> int:
        """Vectors for the person's exchanges that have none from this embedder yet, in the order they were said;
        each one, as it gets its vector, rehearses the earlier exchanges it is about. Returns how many were added
        (0 with no embedder, or while it is not answering: those exchanges are found by their words meanwhile)."""
        meaning = self.meaning
        if meaning is None or meaning.embedder is None:
            return 0
        subject, name = self.who(subject), meaning.name
        rows = self.store.rows("select * from episodes e where space = ? and subject = ? and not exists (select 1 "
                               "from episode_vectors v where v.episode_id = e.id and v.embedder = ?) order by at, id "
                               "limit ?", (self.space, subject, name, limit))
        added = 0
        for start in range(0, len(rows), BATCH):
            batch = [Episode.of(row) for row in rows[start:start + BATCH]]
            vectors = await meaning.embed([self._embedded(episode) for episode in batch])
            if vectors is None:
                break
            # One transaction from here on: an exchange erased (or moved by a link) while it was embedded is left
            # alone, and one another caller embedded meanwhile rehearses nothing twice.
            with self.store.transaction():
                matrix = self._matrix(subject, name)
                bins, pairs = self._spread(subject, name)
                for episode, vector in zip(batch, vectors):
                    if vector is None or self.store.row("select 1 from episodes where id = ? and space = ? and "
                                                        "subject = ?", (episode.id, self.space, subject)) is None:
                        continue
                    if not self.store.execute("insert or ignore into episode_vectors (episode_id, embedder, vector) "
                                              "values (?, ?, ?)", (episode.id, name, pack(vector))).rowcount:
                        continue
                    similarities = matrix.similarities(vector)
                    pairs += tally(bins, similarities)
                    line = threshold(bins, pairs)
                    if line is not None:
                        self._rehearse(matrix.nearest(similarities, episode.at, line), episode.at)
                    matrix.add(episode.id, episode.at, vector)
                    added += 1
                self._put_spread(subject, name, bins, pairs)
        return added

    def _embedded(self, episode: Episode) -> str:
        """What is embedded: the exchange under its date in words ("8 May 2023"), as a person would say it."""
        stamp = dates.local(episode.at, self.zone).strftime("%d %B %Y, %H:%M")
        return f"[{stamp}]\n{episode.text}"

    def _rehearse(self, ids: Iterable[int], now: float) -> None:
        """Each exchange recalled at `now`: its stability grows, the more the further it had faded, and it is fresh."""
        ids = list(ids)
        if not ids:
            return
        for row in self.store.rows(f"select id, at, recalled_at, stability from episodes where id in "
                                   f"({', '.join('?' * len(ids))})", ids):
            last = max(row["at"], row["recalled_at"] or 0.0)
            kept = math.exp(-max(0.0, now - last) / (max(row["stability"], 1e-6) * DAY))
            self.store.execute("update episodes set stability = ?, recalled_at = ?, recalls = recalls + 1 where id = ?",
                               (min(STRONGEST, row["stability"] * (1.5 + 3 * (1 - kept))), max(last, now), row["id"]))

    def forget(self, subject: str, id: int) -> int:
        """An exchange gone for good, its words, index and vectors with it (1), or nothing of this person's by that
        id (0)."""
        with self.writing(subject) as subject:
            found = self.store.row("select id from episodes where id = ? and space = ? and subject = ?",
                                   (id, self.space, subject))
            if found is not None:
                self._delete([found["id"]])
        self._matrices.clear()
        return 0 if found is None else 1

    def erase(self, subject: str) -> int:
        """Every exchange with a person gone for good, with what was learned of their spread; returns how many."""
        with self.writing(subject) as subject:
            ids = [row["id"] for row in self.store.rows("select id from episodes where space = ? and subject = ?",
                                                        (self.space, subject))]
            self._delete(ids)
            self.store.execute("delete from episode_spread where space = ? and subject = ?", (self.space, subject))
        self._matrices.clear()
        return len(ids)

    def _delete(self, ids: list[int]) -> None:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ", ".join("?" * len(chunk))
            for table in ("episode_terms", "episode_vectors"):
                self.store.execute(f"delete from {table} where episode_id in ({marks})", chunk)
            self.store.execute(f"delete from episodes where id in ({marks})", chunk)

    def join(self, old: str, new: str) -> None:
        """`old` is the person `new` now (`People.link`): its exchanges and their index are the person's, and the two
        spreads one."""
        with self.store.transaction():
            for table in ("episodes", "episode_terms"):
                self.store.execute(f"update {table} set subject = ? where space = ? and subject = ?",
                                   (new, self.space, old))
            for row in self.store.rows("select * from episode_spread where space = ? and subject = ?",
                                       (self.space, old)):
                bins, pairs = self._spread(new, row["embedder"])
                theirs = json.loads(row["bins"])
                self._put_spread(new, row["embedder"], [a + b for a, b in zip(bins, theirs)], pairs + row["pairs"])
            self.store.execute("delete from episode_spread where space = ? and subject = ?", (self.space, old))
        self._matrices.clear()

    # ---- reading ---------------------------------------------------------------------------------
    def get(self, id: int) -> Episode | None:
        row = self.store.row("select * from episodes where id = ? and space = ?", (id, self.space))
        return Episode.of(row) if row else None

    def newest(self, subject: str, limit: int = 20) -> list[Episode]:
        """The person's latest exchanges, newest first."""
        rows = self.store.rows("select * from episodes where space = ? and subject = ? order by at desc, id desc "
                               "limit ?", (self.space, self.who(subject), limit))
        return [Episode.of(row) for row in rows]

    def count(self, subject: str | None = None) -> int:
        if subject is None:
            return self.store.row("select count(*) as n from episodes where space = ?", (self.space,))["n"]
        return self.store.row("select count(*) as n from episodes where space = ? and subject = ?",
                              (self.space, self.who(subject)))["n"]

    def retention(self, episode: Episode, now: float | None = None) -> float:
        """How much of it is still remembered (R, from 1 when it was said or rehearsed down to 0)."""
        now = self.clock() if now is None else now
        last = max(episode.at, episode.recalled_at or 0.0)
        return math.exp(-max(0.0, now - last) / (max(episode.stability, 1e-6) * DAY))

    def look(self, subject: str, query: str, *, budget: int = 6000, conversation: str = "", skip: int = 0,
             found=None) -> list[Episode]:
        """What comes to mind for `query` (words only; `alook` adds meaning): the best matches, a faded one counting
        less, within `budget` characters as `render` shows them, in the order they were said. The newest `skip`
        exchanges of `conversation` are left out (the host still shows them)."""
        subject, query = self.who(subject), self._query(query)
        left_out: set[int] = set()
        if skip > 0:
            left_out = {row["id"] for row in self.store.rows(
                "select id from episodes where space = ? and subject = ? and conversation = ? order by at desc, id "
                "desc limit ?", (self.space, subject, conversation, int(skip)))}
        ranked = [id for id in self._ranked(subject, query, found, fade=True) if id not in left_out][:SCANNED]
        chosen, used = [], 0
        for episode in self._get_many(ranked):
            size = len(self.shown(episode)) + 2
            if used + size <= budget:
                chosen.append(episode)
                used += size
            if used > budget - 60:
                break
        return sorted(chosen, key=lambda episode: (episode.at, episode.id))

    async def alook(self, subject: str, query: str, **options) -> list[Episode]:
        """`look` with meaning: the query's vector, if it comes within LOOK_WAIT seconds."""
        found = await self._found(self._query(query), wait=self.LOOK_WAIT)
        return self.look(subject, query, found=found, **options)

    def search(self, subject: str, query: str, *, limit: int = 5, seen: Iterable[int] = (), refresh: bool = True,
               found=None) -> list[Episode]:
        """What a model looks for (words only; `asearch` adds meaning): the best `limit` matches by relevance alone,
        leaving out those in `seen`, in the order they were said. With `refresh`, each is rehearsed: it was
        remembered."""
        subject, query = self.who(subject), self._query(query)
        seen = set(seen)
        fresh = [id for id in self._ranked(subject, query, found, fade=False) if id not in seen][:max(0, limit)]
        if refresh and fresh:
            with self.store.transaction():
                self._rehearse(fresh, self.clock())
        return sorted(self._get_many(fresh), key=lambda episode: (episode.at, episode.id))

    async def asearch(self, subject: str, query: str, **options) -> list[Episode]:
        found = await self._found(self._query(query))
        return self.search(subject, query, found=found, **options)

    def around(self, subject: str, id: int, *, before: int = 1, after: int = 1) -> list[Episode]:
        """An exchange of this person's with the ones said before and after it in the same conversation ([] when
        there is no such exchange of theirs)."""
        subject = self.who(subject)
        episode = self.get(id)
        if episode is None or episode.subject != subject:
            return []
        where = "space = ? and subject = ? and conversation = ?"
        values = (self.space, subject, episode.conversation, episode.at, episode.id)
        earlier = self.store.rows(f"select * from episodes where {where} and (at, id) < (?, ?) order by at desc, id "
                                  f"desc limit ?", (*values, before))
        later = self.store.rows(f"select * from episodes where {where} and (at, id) > (?, ?) order by at, id limit ?",
                                (*values, after))
        return [Episode.of(row) for row in reversed(earlier)] + [episode] + [Episode.of(row) for row in later]

    # ---- showing ---------------------------------------------------------------------------------
    def render(self, episodes: list[Episode], *, user_name: str | None = None, header: str | None = None,
               search: bool = False) -> str:
        """A block for a prompt: a header saying these are data and asking for the person check (is it about this
        person and this thing?), then each exchange with its number and date. `search`: the model has the search
        tool, and is told to look before it says it does not remember. "" with nothing to show."""
        if not episodes:
            return ""
        if header is None:
            header = say(self.words, "said.header", who=user_name or episodes[0].subject) + \
                say(self.words, "said.unsure_search" if search else "said.unsure")
        return "\n\n".join([header, *(self.shown(episode) for episode in episodes)])

    def shown(self, episode: Episode) -> str:
        """One exchange as a model reads it: `#id [date time]`, then its lines; a line's own line breaks are indented,
        so nothing said can pose as another exchange."""
        stamp = dates.local(episode.at, self.zone).strftime("%Y-%m-%d %H:%M")
        lines = [f"#{episode.id} [{stamp}]"]
        for who, said in episode.lines:
            said = fit(said, SHOWN_LINE).replace("\n", "\n  ")
            lines.append(f"{who}: {said}" if who else f"  {said}")
        return "\n".join(lines)

    # ---- ranking ---------------------------------------------------------------------------------
    def _ranked(self, subject: str, query: str, found, *, fade: bool) -> list[int]:
        """The person's exchanges for `query`, best first: BM25 over the search terms (each term once per exchange)
        and closeness to the query's vector, fused by reciprocal rank; with `fade`, each score times
        FLOOR + (1 − FLOOR)·R."""
        rows = self.store.rows("select id, at, recalled_at, stability, size from episodes where space = ? and "
                               "subject = ?", (self.space, subject))
        if not rows:
            return []
        count = len(rows)
        sizes = {row["id"]: row["size"] for row in rows}
        average = sum(sizes.values()) / count or 1.0
        words = getattr(found, "words", "") or ""
        wanted = texts.terms(query + (" " + words if words else ""))
        df: dict[str, int] = {}
        for start in range(0, len(wanted), 400):
            chunk = wanted[start:start + 400]
            df.update({row["term"]: row["n"] for row in self.store.rows(
                f"select term, count(*) as n from episode_terms where space = ? and subject = ? and term in "
                f"({', '.join('?' * len(chunk))}) group by term", (self.space, subject, *chunk))})
        idf = {term: math.log(1 + (count - n + 0.5) / (n + 0.5)) for term, n in df.items()}
        bm25: dict[int, float] = {}
        terms = list(idf)
        for start in range(0, len(terms), 400):
            chunk = terms[start:start + 400]
            for row in self.store.rows(f"select term, episode_id from episode_terms where space = ? and subject = ? "
                                       f"and term in ({', '.join('?' * len(chunk))})", (self.space, subject, *chunk)):
                id = row["episode_id"]
                if id in sizes:
                    bm25[id] = bm25.get(id, 0.0) + idf[row["term"]] * 2.2 / (
                        1 + 1.2 * (0.25 + 0.75 * sizes[id] / average))
        fused: dict[int, float] = {}
        for place, id in enumerate(sorted(bm25, key=lambda id: (-bm25[id], -id))):
            fused[id] = 1 / (RRF + place)
        vector = getattr(found, "vector", None)
        if vector is not None and self.meaning is not None and self.meaning.name:
            matrix = self._matrix(subject, self.meaning.name)
            place = 0
            for index in matrix.order(matrix.similarities(vector)):
                id = matrix.ids[index]
                if id in sizes:  # (still this person's)
                    fused[id] = fused.get(id, 0.0) + 1 / (RRF + place)
                    place += 1
        if fade:
            now = self.clock()
            for row in rows:
                if row["id"] in fused:
                    last = max(row["at"], row["recalled_at"] or 0.0)
                    kept = math.exp(-max(0.0, now - last) / (max(row["stability"], 1e-6) * DAY))
                    fused[row["id"]] *= FLOOR + (1 - FLOOR) * kept
        return sorted(fused, key=lambda id: (-fused[id], -id))

    async def _found(self, query: str, *, wait: float | None = None):
        """What the meaning tiers make of a query (its vector; words, from the unify tier), or None; a recent query
        is not asked twice."""
        if self.meaning is None or not query.strip():
            return None
        if query in self._queries:
            self._queries.move_to_end(query)
            return self._queries[query]
        try:
            found = await (asyncio.wait_for(self.meaning.query(query), wait) if wait else self.meaning.query(query))
        except asyncio.TimeoutError:
            return None
        if getattr(found, "vector", None) is not None or getattr(found, "words", ""):
            self._queries[query] = found
            while len(self._queries) > 32:
                self._queries.popitem(last=False)
        return found

    def _matrix(self, subject: str, name: str) -> _Matrix:
        """The person's vectors from `name`, as they are in the file now (another process may have added some)."""
        key = (subject, name)
        matrix = self._matrices.get(key)
        state = self.store.row("select count(*) as n, max(v.episode_id) as last from episode_vectors v join episodes e "
                               "on e.id = v.episode_id where e.space = ? and e.subject = ? and v.embedder = ?",
                               (self.space, subject, name))
        count, last = state["n"], state["last"] or 0
        select = ("select v.episode_id, e.at, v.vector from episode_vectors v join episodes e on e.id = v.episode_id "
                  "where e.space = ? and e.subject = ? and v.embedder = ?")
        if matrix is not None and count > matrix.read and last > matrix.last:
            for row in self.store.rows(select + " and v.episode_id > ? order by v.episode_id",
                                       (self.space, subject, name, matrix.last)):
                matrix.add(row["episode_id"], row["at"], unpack(row["vector"]))
        if matrix is None or matrix.read != count or matrix.last != last:
            matrix = _Matrix()
            for row in self.store.rows(select + " order by v.episode_id", (self.space, subject, name)):
                matrix.add(row["episode_id"], row["at"], unpack(row["vector"]))
            self._matrices[key] = matrix
        return matrix

    def _spread(self, subject: str, name: str) -> tuple[list[int], int]:
        row = self.store.row("select bins, pairs from episode_spread where space = ? and subject = ? and embedder = ?",
                             (self.space, subject, name))
        if row is None:
            return [0] * BINS, 0
        bins = json.loads(row["bins"])
        return (bins if isinstance(bins, list) and len(bins) == BINS else [0] * BINS), int(row["pairs"])

    def _put_spread(self, subject: str, name: str, bins: list[int], pairs: int) -> None:
        self.store.execute("insert into episode_spread (space, subject, embedder, bins, pairs) values (?, ?, ?, ?, ?) "
                           "on conflict(space, subject, embedder) do update set bins = excluded.bins, pairs = "
                           "excluded.pairs", (self.space, subject, name, dumps(bins), pairs))

    def _get_many(self, ids: list[int]) -> list[Episode]:
        """These exchanges, in the order given."""
        found: dict[int, Episode] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for row in self.store.rows(f"select * from episodes where id in ({', '.join('?' * len(chunk))})", chunk):
                found[row["id"]] = Episode.of(row)
        return [found[id] for id in ids if id in found]

    @staticmethod
    def _query(query) -> str:
        if not isinstance(query, str):
            raise TypeError(f"a query must be a string, not {type(query).__name__}")
        return texts.clean(query)

    # ---- moving between files ----------------------------------------------------------------------
    def export_rows(self) -> dict:
        """This space's exchanges as plain rows (without the caches: terms and vectors)."""
        rows = [{"id": row["id"], "subject": row["subject"], "at": row["at"], "conversation": row["conversation"],
                 "lines": json.loads(row["lines"]), "stability": row["stability"], "recalled_at": row["recalled_at"],
                 "recalls": row["recalls"]}
                for row in self.store.rows("select * from episodes where space = ? order by id", (self.space,))]
        return {"episodes": rows}

    def import_rows(self, rows) -> int:
        """Add exported exchanges to this space, held to the rules of keeping (`clean`); returns how many."""
        added = 0
        with self.store.transaction():
            for original in rows:
                row = self.clean(original, self.days) if isinstance(original, dict) else None
                if row is None:
                    continue
                self._insert(self.who(row.pop("subject")), row)
                added += 1
        self._matrices.clear()
        return added

    @staticmethod
    def clean(row: dict, days: float = 30.0) -> dict | None:
        """An exported exchange held to the rules of keeping, or None when it has no words, subject or time."""
        subject, at = row.get("subject"), dates.seconds(row.get("at"))
        given = row.get("lines")
        if not isinstance(subject, str) or not subject.strip() or at is None or not isinstance(given, list):
            return None
        try:
            lines = lines_of([(item[0], item[1]) for item in given
                              if isinstance(item, (list, tuple)) and len(item) == 2
                              and isinstance(item[0], str) and isinstance(item[1], str)])
        except TypeError:
            return None
        if not lines:
            return None
        try:
            stability = float(row.get("stability"))
        except (TypeError, ValueError, OverflowError):
            stability = days
        stability = min(STRONGEST, stability) if math.isfinite(stability) and stability > 0 else days
        try:
            recalls = max(0, min(2 ** 31, int(row.get("recalls") or 0)))
        except (TypeError, ValueError, OverflowError):
            recalls = 0
        conversation = row.get("conversation")
        return {"subject": subject, "at": at, "lines": lines, "stability": stability,
                "conversation": texts.clip(conversation, 200) if isinstance(conversation, str) else "",
                "recalled_at": dates.seconds(row.get("recalled_at")), "recalls": recalls}
