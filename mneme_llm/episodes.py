"""Episodes: what was said, kept word for word, found again when it matters, fading the way people forget.

A note (`memory.py`) is what the companion made of a conversation; an episode is the conversation itself: one
exchange (the person's message and the reply, each line with who said it), when it was said and in which
conversation. Every exchange the person starts is kept, so nothing said is lost to a note writer that left it out
(on LoCoMo the words beat the notes by 16 to 22 points; docs/DESIGN.md, "Episodes").

They come back two ways:

    look     what comes to mind unprompted, for the message at hand: the best matches within a budget of
             characters, shown in the order they were said. Here an exchange must be close enough to the message,
             and the more it has faded, the closer: fading is what leaves the context. Often nothing comes.
    search   what the model looks for itself, with a tool (`tools.py`): by relevance alone, however faded, so an
             old thing asked about is still found; what it finds is rehearsed, and fades slower from then on.

Ranking is BM25 over the search terms (`text.terms`), fused by reciprocal rank with closeness in meaning (tier 1's
vectors); with no embedder, BM25 alone. Retention is R = e^(−t/S): t the talking days since the exchange was said or
last rehearsed, S its stability (`days`, 30 to start). Only days the person talked count, and a day turns at 4 in the
morning (`dates.talking_day`): someone away for a year comes back to what they left, as nobody forgets by sleeping. A
rehearsal multiplies S by 1.5 + 3·(1 − R), so a thing that comes back just as it was fading lasts much longer, and it
is fresh again. An exchange rehearses the earlier ones it is about: its three nearest in meaning, when they are closer
than 98% of the pairs of this person's exchanges.
"""

from __future__ import annotations

import asyncio
import bisect
import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import tzinfo
from typing import Callable, Iterable, Iterator

from . import dates, exchange as exchanges, text as texts
from .i18n import Speaks, Words, say
from .links import FOLLOW, FROM, LIFT, TOP, Links
from .meaning.vectors import Matrix, numpy, pack, raw
from .people import People, Resolves
from .store import Store, dumps

NEAREST = 3           # the earlier exchanges one exchange may rehearse
SPREAD = 0.98         # ... when closer than this share of the person's pairs
SPREAD_PAIRS = 100    # pairs seen before any exchange rehearses another
BINS = 200            # the spread's histogram: similarity from −1 to 1 in steps of 0.01
MAX_LINE = 8000       # characters of one line kept (its opening and its end, when longer)
MAX_LINES = 40        # lines of one exchange
MAX_NAME = 80         # characters of who said a line
SHOWN_LINE = 2000     # characters of one line a look or a search shows (`read` shows it whole)
RRF = 61              # reciprocal rank fusion: a ranking's place p counts 1 / (RRF + p)
BATCH = 64            # exchanges embedded per request
SCANNED = 200         # the best-ranked exchanges a look reads to fill its budget, at most
READ = 20             # ... this many at a time
MATRICES = 16         # people whose vectors stay in memory (the most recently looked at)
PREPARED = 256        # exchanges a prepare embeds at most (the rest the next time)
BEYOND = 2 ** 63 - 1  # past every id
CUT = 0.08            # a look's bar: an exchange this much closer to the query than the embedder's floor ...
CUT_FADED = 0.16      # ... and, fully faded, this much (in between by its retention); a search has no bar
WORDS = 0.25          # with words alone, the share of the query's weight an exchange must share to be in a look (0: any)
BUDGET = 6000         # characters a look shows
DAYS = 30.0           # S an exchange starts with
STRONGEST = 1e6       # days: stability stops growing here
EXCHANGE = 2.4        # tokens two messages cost beyond their words
NEWEST = 64           # exchanges read at a time, the newest first
MIND = 600            # seconds what a look brought stays on her mind for the exchange kept after it


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
    day: int = 0                    # its talking day (`dates.talking_day`)
    tokens: float = 0.0             # about what a model counts in it (`cost`)

    @property
    def text(self) -> str:
        return exchanges.text_of(self.lines)

    @classmethod
    def of(cls, row) -> "Episode":
        lines = tuple((str(who), str(said)) for who, said in json.loads(row["lines"]))
        return cls(row["id"], row["subject"], row["at"], row["conversation"], lines, row["stability"],
                   row["recalled_at"], row["recalls"], row["day"], row["tokens"])


def lines_of(exchange) -> list[tuple[str, str]]:
    """An exchange's lines as they are kept: who said each (one line) and what (cleaned; the opening and the end of
    a very long one), empty ones left out, at most MAX_LINES."""
    kept = []
    for who, said in exchanges.as_lines(exchange):
        said = texts.clean(said).strip()
        if texts.blank(said):
            continue
        kept.append((texts.clip(who, MAX_NAME), texts.fit(said, MAX_LINE)))
    return kept[:MAX_LINES]


def cost(lines) -> float:
    """About how many tokens an exchange comes to in a model's context."""
    return texts.tokens(exchanges.text_of(lines)) + EXCHANGE


def _terms(lines) -> list[str]:
    """What an exchange is found by: what was said, not who said it (they are in every one)."""
    return texts.terms(" ".join(said for _, said in lines))


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

    def __init__(self, store: Store, space: str, *, days: float = DAYS, zone: tzinfo | None = None,
                 display_language: str | Words = "en", meaning=None, people: People | None = None,
                 clock: Callable[[], float] = time.time):
        self.store, self.space, self.days, self.people = store, space, days, people
        self.words = Words.of(display_language)
        self.zone, self.meaning, self.clock = zone, meaning, clock
        self._matrices: OrderedDict[tuple[str, str], Matrix] = OrderedDict()
        self._queries: OrderedDict[str, object] = OrderedDict()  # recent queries' vectors (a turn asks again)
        self.links = Links(store, space, zone=zone, clock=clock)  # what reminds her of what (`links.py`)
        self._mind: dict[str, tuple[float, list[int]]] = {}  # what her last own look brought, by person, and when
        store.index("episode_terms", self._reindex)

    # ---- writing ---------------------------------------------------------------------------------
    def keep(self, subject: str, exchange, *, at: float | None = None, conversation: str = "") -> Episode | None:
        """Keep an exchange word for word (a string, or `(who, said)` pairs or chat messages); returns it, or None
        when it has no words. `at` is when it was said (now when not given); `conversation` is where (a chat, a
        channel: any name of the host's)."""
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
            if self.store.row("select 1 from episodes where space = ? and subject = ? and day = ? and id != ? limit 1",
                              (self.space, subject, dates.talking_day(when, self.zone), id)) is None:
                self.links.sleep(subject, when)  # the first of a talking day: she has slept (`links.py`)
            looked, mind = self._mind.pop(subject, (0.0, []))
            if mind and 0 <= when - looked <= MIND:  # what was on her mind as it was said (`links.py`)
                self.links.born(subject, [(id, other, 0.0) for other in mind], when)
        return self.get(id)

    async def akeep(self, subject: str, exchange, **options) -> Episode | None:
        """`keep`, then its vector (meaning tier 1), with which it rehearses the earlier exchanges it is about."""
        episode = self.keep(subject, exchange, **options)
        if episode is not None:
            await self.prepare(episode.subject, first=[episode.id])
        return episode

    def _insert(self, subject: str, row: dict) -> int:
        terms = _terms(row["lines"])
        id = self.store.execute("insert into episodes (space, subject, at, day, conversation, lines, size, tokens, "
                                "stability, recalled_at, recalls) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (self.space, subject, row["at"], dates.talking_day(row["at"], self.zone),
                                 row["conversation"], dumps(row["lines"]), len(terms), cost(row["lines"]),
                                 row["stability"], row["recalled_at"], row["recalls"])).lastrowid
        self._index(self.space, subject, id, terms)
        return id

    def _index(self, space: str, subject: str, id: int, terms: list[str]) -> None:
        for term in terms:
            self.store.execute("insert into episode_terms (space, subject, term, episode_id) values (?, ?, ?, ?)",
                               (space, subject, term, id))

    def _reindex(self) -> None:
        """Every exchange of the file in the term index again (`Store.reindex`)."""
        self.store.execute("delete from episode_terms")
        for row in self.store.rows("select id, space, subject, lines from episodes"):
            terms = _terms(json.loads(row["lines"]))
            self.store.execute("update episodes set size = ? where id = ?", (len(terms), row["id"]))
            self._index(row["space"], row["subject"], row["id"], terms)

    async def prepare(self, subject: str, *, limit: int = PREPARED, first: Iterable[int] = ()) -> int:
        """Vectors for the person's exchanges that have none from this embedder yet: those in `first` (the ones
        just kept), then the rest in the order they were said, at most `limit` in all (a long backlog, an embedder
        turned on late, is caught up a little at each exchange). Each one, as it gets its vector, rehearses the
        earlier exchanges it is about. Returns how many were added (0 with no embedder, or while it is not
        answering: those exchanges are found by their words meanwhile)."""
        meaning = self.meaning
        if meaning is None or meaning.embedder is None:
            return 0
        subject, name = self.who(subject), meaning.name
        missing = ("select * from episodes e where space = ? and subject = ? and not exists (select 1 from "
                   "episode_vectors v where v.episode_id = e.id and v.embedder = ?)")
        first = [int(id) for id in first][:limit]
        rows = self.store.rows_in(f"{missing} and id in ({{}}) order by at, id", first, (self.space, subject, name))
        rows += [row for row in self.store.rows(f"{missing} order by at, id limit ?",
                                                (self.space, subject, name, limit))
                 if row["id"] not in set(first)][:limit - len(rows)]
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
                        near = matrix.nearest(similarities, episode.at, line, NEAREST)
                        self._rehearse(near, episode.at)
                        # what it reminded her of, linked to it (`links.py`)
                        self.links.born(subject, [(episode.id, id, float(similarities[matrix.ids.index(id)]))
                                                  for id in near], episode.at)
                    matrix.add(episode.id, vector, episode.at)
                    added += 1
                self._put_spread(subject, name, bins, pairs)
        return added

    def _embedded(self, episode: Episode) -> str:
        """What is embedded: the exchange under its date in words ("8 May 2023"), as a person would say it."""
        stamp = dates.local(episode.at, self.zone).strftime("%d %B %Y, %H:%M")
        return f"[{stamp}]\n{episode.text}"

    def talking_days(self, subject: str) -> list[int]:
        """The person's talking days, in order: the days an exchange of theirs was kept (`dates.talking_day`)."""
        return [row["day"] for row in self.store.rows("select distinct day from episodes where space = ? and subject "
                                                      "= ? order by day", (self.space, self.who(subject)))]

    def _kept(self, row, today: int, days: list[int]) -> float:
        """R of an exchange (or its row): t counts the talking days after its last day, up to `today`, which is one
        because they are talking now."""
        since = row["day"]
        if row["recalled_at"] is not None and row["recalled_at"] > row["at"]:
            since = dates.talking_day(row["recalled_at"], self.zone)
        passed = bisect.bisect_left(days, today) - bisect.bisect_right(days, since) + 1 if today > since else 0
        return math.exp(-passed / max(row["stability"], 1e-6))

    def _rehearse(self, ids: Iterable[int], now: float) -> None:
        """Each exchange recalled at `now`, at most once a talking day: its stability grows, the more the further it had
        faded, and it is fresh."""
        today, talked = dates.talking_day(now, self.zone), {}
        for row in self.store.rows_in("select id, subject, at, day, recalled_at, stability from episodes where id in "
                                      "({})", ids):
            if row["recalled_at"] is not None and dates.talking_day(row["recalled_at"], self.zone) >= today:
                continue  # (and a late vector's, from before the last one, counts nothing)
            if row["subject"] not in talked:
                talked[row["subject"]] = self.talking_days(row["subject"])
            kept = self._kept(row, today, talked[row["subject"]])
            self.store.execute("update episodes set stability = ?, recalled_at = ?, recalls = recalls + 1 where id = ?",
                               (min(STRONGEST, row["stability"] * (1.5 + 3 * (1 - kept))),
                                max(row["at"], row["recalled_at"] or 0.0, now), row["id"]))

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
            self.links.erase(subject)
            self.store.execute("delete from episode_spread where space = ? and subject = ?", (self.space, subject))
        self._matrices.clear()
        return len(ids)

    def _delete(self, ids: list[int]) -> None:
        for table in ("episode_terms", "episode_vectors"):
            self.store.rows_in(f"delete from {table} where episode_id in ({{}})", ids)
        self.links.forget(ids)
        self.store.rows_in("delete from episodes where id in ({})", ids)

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
            self.links.join(old, new)
        self._matrices.clear()

    # ---- reading ---------------------------------------------------------------------------------
    def get(self, id: int) -> Episode | None:
        row = self.store.row("select * from episodes where id = ? and space = ?", (id, self.space))
        return Episode.of(row) if row else None

    def after(self, subject: str, start_id: int, budget: float | None = None, *,
              before: int = BEYOND) -> list[Episode]:
        """The person's exchanges with an id after `start_id` (and before `before`), the newest first, whole, within
        `budget` tokens when one is given, and always the newest, even alone over it. They are read a few at a time, so
        a small budget reads little however much there is."""
        subject, found, used = self.who(subject), [], 0.0
        while True:
            rows = self.store.rows("select * from episodes where space = ? and subject = ? and id > ? and id < ? order "
                                   "by id desc limit ?", (self.space, subject, start_id, before, NEWEST))
            for row in rows:
                if budget is not None and found and used + row["tokens"] > budget:
                    return found
                found.append(Episode.of(row))
                used += row["tokens"]
            if len(rows) < NEWEST:
                return found
            before = rows[-1]["id"]

    def tokens_after(self, subject: str, start_id: int, *, days: int | None = None) -> float:
        """How many tokens the person's exchanges after `start_id` come to; with `days`, only those of their last so
        many talking days."""
        subject = self.who(subject)
        edge = self.talking_days(subject)[-days:][:1] if days else []
        return self.store.row("select coalesce(sum(tokens), 0) as n from episodes where space = ? and subject = ? and "
                              "id > ? and day >= ?", (self.space, subject, start_id, edge[0] if edge else 0))["n"]

    def latest(self, subject: str, before: float = dates.LATEST) -> tuple[int, float]:
        """The highest id among the person's exchanges said before `before`, and the latest moment one was said (0, 0.0
        with none)."""
        row = self.store.row("select coalesce(max(id), 0) as id, coalesce(max(at), 0.0) as at from episodes where "
                             "space = ? and subject = ? and at < ?", (self.space, self.who(subject), before))
        return row["id"], row["at"]

    def holds(self, subject: str) -> bool:
        """Whether any exchange is kept under exactly this subject, linked or not."""
        return self.store.row("select 1 from episodes where space = ? and subject = ? limit 1",
                              (self.space, subject)) is not None

    def subjects(self) -> list[str]:
        """Everyone an exchange is kept of."""
        return [row["subject"] for row in self.store.rows("select distinct subject from episodes where space = ? order "
                                                          "by subject", (self.space,))]

    def count(self, subject: str | None = None) -> int:
        if subject is None:
            return self.store.row("select count(*) as n from episodes where space = ?", (self.space,))["n"]
        return self.store.row("select count(*) as n from episodes where space = ? and subject = ?",
                              (self.space, self.who(subject)))["n"]

    def retention(self, episode: Episode, now: float | None = None) -> float:
        """How much of it is still remembered (R, from 1 when it was said or rehearsed down to 0)."""
        now = self.clock() if now is None else now
        return self._kept({"at": episode.at, "day": episode.day, "recalled_at": episode.recalled_at,
                           "stability": episode.stability}, dates.talking_day(now, self.zone),
                          self.talking_days(episode.subject))

    def look(self, subject: str, query: str, *, budget: int = BUDGET,
             cut: tuple[float, float] | None = (CUT, CUT_FADED), more: int = 0, found=None,
             skip=None, words_cut: float = WORDS, follow: int = FOLLOW, lift: float = LIFT, use: bool = False,
             brought: dict | None = None) -> list[Episode]:
        """What comes to mind for `query` (words only; `alook` adds meaning): the best matches within `budget`
        characters as `render` shows them, in the order they were said. With the query's vector from the embedder, an
        exchange must clear a bar: its cosine with the query at least the embedder's floor as the bundled set placed
        it (the similarity under which a text says nothing about a query, `Meaning.set_floor`) plus `cut[0]` when
        fresh, plus `cut[1]` when fully faded, in between by its retention. One under its bar is left out however much
        budget is left, so a look may be short, or empty (`cut=None`: no bar). With words alone the bar is `words_cut`: the
        terms an exchange shares with the query carry at least that share of the query's weight (each term by its idf,
        so a common single character counts for little; 0: no bar). `more`
        adds that many more of the best by relevance alone, however faded, as a search would find them, rehearsing
        nothing. `skip`: ids left out, such as what the conversation in front of the model still shows.

        `follow` follows links one step (`links.py`): the heaviest links of the best `FROM` that came bring up to
        `follow` more, in place of the weakest of the rest, each within `lift` of the bar its closeness is held to
        (with meaning only: with words alone nothing is followed). `brought` (a dict) is filled with each that came so,
        and the exchange that brought it. `use`: this look is her own: the best `TOP` that came, and each with what
        brought it, came to mind together (`Links.born`), and they are on her mind for the exchange kept next."""
        subject, query = self.who(subject), texts.query(query)
        misses: dict[int, float] | None = {} if follow > 0 else None
        order, cleared = self._ranked(subject, query, found, cut=cut, words_cut=words_cut, misses=misses)
        if skip:
            order = [id for id in order if id not in skip]
        chosen = self._fill(order, cleared, budget)  # (the best first)
        followed: dict[int, int] = {}
        if misses is not None and (misses or cleared) and getattr(found, "vector", None) is not None:
            taken = {episode.id for episode in chosen}
            near = self.links.neighbours(subject, [episode.id for episode in chosen[:FROM]])
            for id in sorted(near, key=lambda id: (-near[id][0], id)):
                if len(followed) >= follow:
                    break
                if id not in taken and not (skip and id in skip) and (id in cleared or misses.get(id, 1.0) <= lift):
                    followed[id] = near[id][1]
            if followed:
                extra, room = [], budget
                for episode in self._get_many(list(followed)):
                    size = len(self.shown(episode)) + 2
                    if size <= room:
                        extra.append(episode)
                        room -= size
                kept, used = [], 0
                for episode in chosen:  # the best first: the weakest give way
                    size = len(self.shown(episode)) + 2
                    if used + size <= room:
                        kept.append(episode)
                        used += size
                chosen = kept + extra
                followed = {episode.id: followed[episode.id] for episode in extra}
        if brought is not None:
            brought.update(followed)
        if use and chosen:
            best = [episode.id for episode in chosen if episode.id not in followed][:TOP]
            pairs = [(one, other, 0.0) for index, one in enumerate(best) for other in best[index + 1:]]
            with self.store.transaction():
                self.links.born(subject, pairs + [(id, via, 0.0) for id, via in followed.items()], self.clock())
            self._mind[subject] = (self.clock(), best)
        taken = {episode.id for episode in chosen}
        chosen += self._get_many([id for id in order if id not in taken][:max(0, more)])
        return sorted(chosen, key=lambda episode: (episode.at, episode.id))

    def _fill(self, order: list[int], cleared: set[int], budget: int) -> list[Episode]:
        """The best of `order` that are in `cleared`, as many as `budget` characters show."""
        chosen, used = [], 0
        for episode in self._get_many([id for id in order if id in cleared][:SCANNED]):
            size = len(self.shown(episode)) + 2
            if used + size <= budget:
                chosen.append(episode)
                used += size
            if used > budget - 60:
                break
        return chosen

    async def alook(self, subject: str, query: str, **options) -> list[Episode]:
        """`look` with meaning: the query's vector, if it comes within LOOK_WAIT seconds."""
        found = await self._found(texts.query(query), wait=self.LOOK_WAIT)
        return self.look(subject, query, found=found, **options)

    def search(self, subject: str, query: str, *, limit: int = 5, seen: Iterable[int] = (), refresh: bool = True,
               found=None) -> list[Episode]:
        """What a model looks for (words only; `asearch` adds meaning): the best `limit` matches by relevance alone,
        leaving out those in `seen`, in the order they were said. With `refresh`, each is rehearsed: it was
        remembered."""
        subject, query = self.who(subject), texts.query(query)
        seen = set(seen)
        fresh = [id for id in self._ranked(subject, query, found)[0] if id not in seen][:max(0, limit)]
        if refresh and fresh:
            with self.store.transaction():
                self._rehearse(fresh, self.clock())
        return sorted(self._get_many(fresh), key=lambda episode: (episode.at, episode.id))

    async def asearch(self, subject: str, query: str, **options) -> list[Episode]:
        found = await self._found(texts.query(query))
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
    def render(self, episodes: list[Episode], *, user_name: str | None = None, search: bool = False,
               own: bool = False) -> str:
        """A block for a prompt: a header saying these are data and asking for the person check (is it about this
        person and this thing?), then each exchange with its number and date. `own`: it is the person's own
        conversation with the companion, what they said to it in the first place, so the header only says what this
        is. `search`: the model has the search tool, and is told to look before it says it does not remember; with
        nothing to show, that is all it is told ("" without `search`)."""
        if not episodes:
            return say(self.words, "said.none_search") if search else ""
        header = say(self.words, "said.own" if own else "said.header", who=user_name or episodes[0].subject) + \
            say(self.words, "said.unsure_search" if search else "said.unsure")
        return "\n\n".join([header, *(self.shown(episode) for episode in episodes)])

    def shown(self, episode: Episode, *, whole: bool = False) -> str:
        """One exchange as a model reads it: `#id [date time]`, then its lines, each up to SHOWN_LINE characters (its
        opening and its end) unless `whole`; a line's own line breaks are indented, so nothing said can pose as
        another exchange."""
        stamp = dates.local(episode.at, self.zone).strftime("%Y-%m-%d %H:%M")
        lines = [f"#{episode.id} [{stamp}]"]
        for who, said in episode.lines:
            said = (said if whole else texts.fit(said, SHOWN_LINE)).replace("\n", "\n  ")
            lines.append(f"{who}: {said}" if who else f"  {said}")
        return "\n".join(lines)

    # ---- ranking ---------------------------------------------------------------------------------
    def _ranked(self, subject: str, query: str, found, *, cut: tuple[float, float] | None = None,
                words_cut: float = 0.0, misses: dict | None = None) -> tuple[list[int], set[int]]:
        """The person's exchanges for `query`, best first (BM25 over the search terms, each term once per exchange, and
        closeness to the query's vector, fused by reciprocal rank), and which of them clear the bar of `cut`, or of
        `words_cut` when the query has no vector (see `look`); fading changes nothing else. `misses` (a dict) is filled
        with how far each one under the bar of `cut` is under it."""
        self.store.reindex()
        rows = self.store.rows("select id, at, day, recalled_at, stability, size from episodes where space = ? and "
                               "subject = ?", (self.space, subject))
        if not rows:
            return [], set()
        count = len(rows)
        sizes = {row["id"]: row["size"] for row in rows}
        average = sum(sizes.values()) / count or 1.0
        words = getattr(found, "words", "") or ""
        wanted = texts.terms(query + (" " + words if words else ""))
        mine = (self.space, subject)
        df = {row["term"]: row["n"] for row in self.store.rows_in(
            "select term, count(*) as n from episode_terms where space = ? and subject = ? and term in ({}) group by "
            "term", wanted, mine)}
        idf = {term: math.log(1 + (count - n + 0.5) / (n + 0.5)) for term, n in df.items()}
        bm25: dict[int, float] = {}
        shared: dict[int, float] = {}  # (the weight of the query's terms each exchange has)
        for row in self.store.rows_in("select term, episode_id from episode_terms where space = ? and subject = ? and "
                                      "term in ({})", list(idf), mine):
            id = row["episode_id"]
            if id in sizes:
                bm25[id] = bm25.get(id, 0.0) + idf[row["term"]] * 2.2 / (1 + 1.2 * (0.25 + 0.75 * sizes[id] / average))
                shared[id] = shared.get(id, 0.0) + idf[row["term"]]
        fused: dict[int, float] = {}
        for place, id in enumerate(sorted(bm25, key=lambda id: (-bm25[id], -id))):
            fused[id] = 1 / (RRF + place)
        vector = getattr(found, "vector", None)
        close: dict[int, float] = {}
        if vector is not None and self.meaning is not None and self.meaning.name:
            matrix = self._matrix(subject, self.meaning.name)
            similarities = matrix.similarities(vector)
            place = 0
            for index in matrix.order(similarities):
                id = matrix.ids[index]
                if id in sizes:  # (still this person's)
                    fused[id] = fused.get(id, 0.0) + 1 / (RRF + place)
                    close[id] = float(similarities[index])
                    place += 1
        order, cleared = sorted(fused, key=lambda id: (-fused[id], -id)), set(fused)
        if cut is not None and words_cut > 0 and vector is None:
            whole = sum(idf.values()) or 1.0
            cleared = {id for id in cleared if shared.get(id, 0.0) / whole >= words_cut}
        if cut is not None and close:
            floor = self.meaning.set_floor
            fresh, faded = floor + cut[0], floor + cut[1]
            today, days = dates.talking_day(self.clock(), self.zone), self.talking_days(subject)
            for row in rows:
                id = row["id"]
                if id in close:  # (one with no vector yet is not judged)
                    bar = fresh + (1 - self._kept(row, today, days)) * (faded - fresh)
                    if close[id] < bar:
                        cleared.discard(id)
                        if misses is not None:
                            misses[id] = bar - close[id]
        return order, cleared

    async def _found(self, query: str, *, wait: float | None = None):
        """What the meaning tiers make of a query (its vector; words, from the unify tier), or None; a recent query
        is not asked twice."""
        if self.meaning is None or not query.strip():
            return None
        known = self._queries.get(query)
        if known is not None and (known.tier == "embeddings" or not self.meaning.rest.up()):
            self._queries.move_to_end(query)
            return known
        try:
            found = await (asyncio.wait_for(self.meaning.query(query), wait) if wait else self.meaning.query(query))
        except asyncio.TimeoutError:
            return known  # (what a lower tier made of it, if it was asked before)
        if getattr(found, "vector", None) is not None or getattr(found, "words", ""):
            self._queries[query] = found
            while len(self._queries) > 32:
                self._queries.popitem(last=False)
        return found

    def _matrix(self, subject: str, name: str) -> Matrix:
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
                matrix.add(row["episode_id"], raw(row["vector"]), row["at"])
        if matrix is None or matrix.read != count or matrix.last != last:
            matrix = Matrix()
            for row in self.store.rows(select + " order by v.episode_id", (self.space, subject, name)):
                matrix.add(row["episode_id"], raw(row["vector"]), row["at"])
            self._matrices[key] = matrix
        self._matrices.move_to_end(key)
        while len(self._matrices) > MATRICES:
            self._matrices.popitem(last=False)
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

    def _get_many(self, ids: list[int]) -> Iterator[Episode]:
        """These exchanges, in the order given, read a few at a time: a look stops at its budget."""
        for start in range(0, len(ids), READ):
            chunk = ids[start:start + READ]
            found = {row["id"]: Episode.of(row) for row in self.store.rows_in("select * from episodes where id in ({})",
                                                                              chunk)}
            yield from (found[id] for id in chunk if id in found)

    # ---- moving between files ----------------------------------------------------------------------
    def export_rows(self) -> dict:
        """This space's exchanges as plain rows (without the caches: terms and vectors)."""
        rows = [{"id": row["id"], "subject": row["subject"], "at": row["at"], "conversation": row["conversation"],
                 "lines": json.loads(row["lines"]), "stability": row["stability"], "recalled_at": row["recalled_at"],
                 "recalls": row["recalls"]}
                for row in self.store.rows("select * from episodes where space = ? order by id", (self.space,))]
        return {"episodes": rows}

    def import_rows(self, rows) -> int:
        """Add exported exchanges to this space, held to the rules of keeping (`clean`), each one once: an exchange
        already here (same person, time, conversation and words) is not added again. Returns how many were."""
        added = 0
        with self.store.transaction():
            for original in rows:
                row = self.clean(original, self.days) if isinstance(original, dict) else None
                if row is None:
                    continue
                subject = self.who(row.pop("subject"))
                if self.store.row("select 1 from episodes where space = ? and subject = ? and at = ? and "
                                  "conversation = ? and lines = ?", (self.space, subject, row["at"],
                                                                     row["conversation"], dumps(row["lines"]))):
                    continue
                self._insert(subject, row)
                added += 1
        self._matrices.clear()
        return added

    @staticmethod
    def clean(row: dict, days: float = DAYS) -> dict | None:
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
