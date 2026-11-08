"""Links: what reminds her of what. Two exchanges of one person, joined because they came to mind together.

An exchange (`episodes.py`) is one memory. A link joins two of them, and nothing but what already happens makes one:
no model call. It is born, or used if it is there, when

    reminded    a new exchange, as it gets its vector, rehearses an earlier one it is about (`Episodes.prepare`: its
                nearest few, closer than almost every pair of this person's exchanges)
    on her mind a new exchange is kept while a look for its message had brought an earlier one (the best `TOP`)
    together    two exchanges come to mind for one message (among the best `TOP` of her own look), or one brings the
                other (below)

A link fades as an exchange does: R = e^(−t/S), t the talking days since it was born or last used, S its stability
(`days`, 30 to start). A use counts at most once a talking day, and makes it last longer, the more the further it had
faded. Its weight is R × (1 + its uses): what came to mind together again and again outweighs a coincidence. One faded
under `FLOOR` is gone at the next day's turn (`sleep`), and an exchange keeps at most `MOST` links, the heaviest.

A look can follow them one step (`Episodes.look`, `follow`): the heaviest links of the best `FROM` exchanges that came
to mind bring up to `follow` more, in place of the weakest of the rest, when they are within `lift` of the look's bar.
With `follow` 0 they are kept and drawn, and a look is as it was.

A link never joins two people: what one person said must not bring back what another told her. Forgetting an
exchange takes its links with it; two subjects joined into one person (`People.link`) keep theirs.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Iterable

from . import dates
from .store import Store

DAYS = 30.0        # S a link starts with
STRONGEST = 1e6    # days: stability stops growing here
FLOOR = 0.05       # R under which a link is gone at the next sleep
MOST = 8           # links one exchange keeps, the heaviest
TOP = 3            # the best of a look that are on her mind (linked to the next exchange kept, and to each other)
FROM = 5           # the best of a look whose links it follows
FOLLOW = 0         # exchanges a look may bring by links (0: links are not followed)
LIFT = 0.1         # ... each at most this far under the look's bar


def retention(day: int, stability: float, today: int, days: list[int]) -> float:
    """R of something last renewed on talking day `day`: t counts the person's talking days after it, up to `today`
    (as `Episodes._kept` counts them)."""
    passed = bisect.bisect_left(days, today) - bisect.bisect_right(days, day) + 1 if today > day else 0
    return math.exp(-passed / max(stability, 1e-6))


@dataclass(frozen=True)
class Link:
    a: int              # the earlier exchange's id
    b: int              # the later one's
    closeness: float    # how close in meaning the two were when it was born (cosine)
    day: int            # the talking day it was born or last used
    stability: float
    uses: int
    strength: float     # R now

    @property
    def weight(self) -> float:
        return self.strength * (1 + self.uses)


class Links:
    """The links of one space's exchanges."""

    def __init__(self, store: Store, space: str, *, days: float = DAYS, zone=None, clock=None):
        self.store, self.space, self.days, self.zone, self.clock = store, space, days, zone, clock

    # ---- what the person's days are --------------------------------------------------------------------------------
    def _days(self, subject: str) -> list[int]:
        return [row["day"] for row in self.store.rows("select distinct day from episodes where space = ? and subject "
                                                      "= ? order by day", (self.space, subject))]

    def _today(self, at: float | None = None) -> int:
        return dates.talking_day(self.clock() if at is None else at, self.zone)

    def _of(self, row, today: int, days: list[int]) -> Link:
        return Link(row["a"], row["b"], row["closeness"], row["day"], row["stability"], row["uses"],
                    retention(row["day"], row["stability"], today, days))

    # ---- writing ---------------------------------------------------------------------------------------------------
    def born(self, subject: str, pairs: Iterable[tuple[int, int, float]], at: float) -> int:
        """Each of `pairs` ((one, other, closeness): closeness in meaning, 0 when not known) came to mind together at
        `at`: a link between them, or, where there is one, a use of it. Each end then keeps its `MOST` heaviest. Returns
        how many were born."""
        today, made, ends, known = self._today(at), 0, set(), []
        for one, other, closeness in pairs:
            if one == other:
                continue
            a, b = min(one, other), max(one, other)
            if self.store.execute("insert or ignore into links (space, subject, a, b, closeness, day, stability, uses) "
                                  "values (?, ?, ?, ?, ?, ?, ?, 0)", (self.space, subject, a, b, float(closeness),
                                                                     today, self.days)).rowcount:
                made += 1
                ends.update((a, b))
            else:
                known.append((a, b))
        if known:
            self.used(subject, followed=known, at=at)
        if made:
            days = self._days(subject)
            for end in ends:
                self._keep_heaviest(end, today, days)
        return made

    def _keep_heaviest(self, end: int, today: int, days: list[int]) -> None:
        rows = self.store.rows("select * from links where space = ? and (a = ? or b = ?)", (self.space, end, end))
        if len(rows) <= MOST:
            return
        lightest = sorted(rows, key=lambda row: (self._of(row, today, days).weight, row["closeness"]))
        for row in lightest[:len(rows) - MOST]:
            self.store.execute("delete from links where space = ? and a = ? and b = ?", (self.space, row["a"], row["b"]))

    def used(self, subject: str, together: Iterable[int] = (), followed: Iterable[tuple[int, int]] = (),
             at: float | None = None) -> int:
        """Links used at `at`: every one between two of `together` (they came to mind for one message) and each of
        `followed` ((from, to): one brought the other). Each is renewed at most once a talking day: R back to 1 and S
        longer, the more the further it had faded. Returns how many were."""
        together = sorted({int(id) for id in together})
        pairs = {(min(a, b), max(a, b)) for a, b in followed}
        if len(together) > 1:
            pairs.update((row["a"], row["b"]) for row in self._between(together))
        if not pairs:
            return 0
        today, days, renewed = self._today(at), self._days(subject), 0
        for a, b in pairs:
            row = self.store.row("select * from links where space = ? and a = ? and b = ?", (self.space, a, b))
            if row is None or row["day"] >= today:
                continue
            kept = retention(row["day"], row["stability"], today, days)
            self.store.execute("update links set day = ?, stability = ?, uses = uses + 1 where space = ? and a = ? and "
                               "b = ?", (today, min(STRONGEST, row["stability"] * (1.5 + 3 * (1 - kept))),
                                         self.space, a, b))
            renewed += 1
        return renewed

    def _between(self, ids: list[int]) -> list:
        """The links with both ends among `ids`."""
        wanted, found = set(ids), []
        for row in self.store.rows_in("select a, b from links where space = ? and a in ({})", ids, (self.space,)):
            if row["b"] in wanted:
                found.append(row)
        return found

    def sleep(self, subject: str, at: float | None = None) -> int:
        """The day's turn: links faded under `FLOOR` are gone, and those to an exchange no longer there (one a program
        that does not know links forgot). Returns how many."""
        today, days = self._today(at), self._days(subject)
        here = {row["id"] for row in self.store.rows("select id from episodes where space = ? and subject = ?",
                                                      (self.space, subject))}
        gone = [(row["a"], row["b"]) for row in self.store.rows("select * from links where space = ? and subject = ?",
                                                                 (self.space, subject))
                if row["a"] not in here or row["b"] not in here
                or retention(row["day"], row["stability"], today, days) < FLOOR]
        for a, b in gone:
            self.store.execute("delete from links where space = ? and a = ? and b = ?", (self.space, a, b))
        return len(gone)

    def forget(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        self.store.rows_in("delete from links where space = ? and a in ({})", ids, (self.space,))
        self.store.rows_in("delete from links where space = ? and b in ({})", ids, (self.space,))

    def erase(self, subject: str) -> None:
        self.store.execute("delete from links where space = ? and subject = ?", (self.space, subject))

    def join(self, old: str, new: str) -> None:
        self.store.execute("update links set subject = ? where space = ? and subject = ?", (new, self.space, old))

    # ---- reading ---------------------------------------------------------------------------------------------------
    def neighbours(self, subject: str, ids: Iterable[int], at: float | None = None) -> dict[int, tuple[float, int]]:
        """The exchanges linked to any of `ids` and not among them: each with the heaviest such link's weight and the
        exchange at its other end."""
        ids = list({int(id) for id in ids})
        if not ids:
            return {}
        today, days, found = self._today(at), self._days(subject), {}
        wanted = set(ids)
        rows = self.store.rows_in("select * from links where space = ? and a in ({})", ids, (self.space,))
        rows += self.store.rows_in("select * from links where space = ? and b in ({})", ids, (self.space,))
        for row in rows:
            for here, there in ((row["a"], row["b"]), (row["b"], row["a"])):
                if here in wanted and there not in wanted:
                    weight = self._of(row, today, days).weight
                    if weight > found.get(there, (0.0, 0))[0]:
                        found[there] = (weight, here)
        return found

    def all(self, subject: str, at: float | None = None) -> list[Link]:
        """Every link of the person's, the strongest first."""
        today, days = self._today(at), self._days(subject)
        return sorted((self._of(row, today, days) for row in self.store.rows(
            "select * from links where space = ? and subject = ?", (self.space, subject))),
            key=lambda link: (-link.weight, -link.closeness, link.a, link.b))

    def count(self, subject: str | None = None) -> int:
        if subject is None:
            return self.store.row("select count(*) as n from links where space = ?", (self.space,))["n"]
        return self.store.row("select count(*) as n from links where space = ? and subject = ?",
                              (self.space, subject))["n"]
