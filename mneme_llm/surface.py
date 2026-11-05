"""The surface: what was said lately, as real turns, in front of the deep memory that holds every word.

Everything said is kept word for word the moment it is said (`episodes.py`): that is deep memory, and compaction never
touches it. The surface is not a second store: nothing is kept twice, it is only where the newest part of deep memory
starts, the exchanges with an id after `start_id`. Whoever sends the context compacts it. A host that sends `read` lets
`alet_go` shorten it; one that keeps a context of its own compacts that itself, and reads only what must be the same on
any host (`slice`).

How much it keeps counts talking days, as fading does (`dates.talking_day`). It keeps what the last `days` talking days
hold, but never less than `floor` tokens, so six messages a day are not summarised after a month. Nothing leaves until
it holds twice that; then the older part becomes one summary, its words still in deep memory. `cap` is the top whatever
the rest says, or 80% of `window` on a smaller model:

    keep = min(max(floor, last days), 2/3 cap)      top = min(2 keep, cap)

A Character Card is kept here too: who the companion is to be, in a person's own words, kept out of the conversation,
where it does not fade. At first it is the first thing they said, which is usually that (`noticed`); it can be set
(`set_card`). It is used only once it is turned on (`card_on`), since what someone said first may be what they have grown
away from. On, the host puts it in its system prompt (`card`), which every call carries and no compaction reaches, so it
is not lost as a conversation grows. Whose card a host uses is its own choice: the DSH plugin uses its owner's.
Dropped, its row stays with no text, so the next thing they say does not become it. The surface follows the person into
any chat.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from . import dates, providers, text as texts
from .i18n import Speaks, Words, fill, say
from .people import People, Resolves
from .prompts import PROMPTS
from .store import Store

FLOOR = 70_000      # tokens it never keeps less than
CAP = 504_000       # tokens it never holds more than
WINDOW = 1_048_576  # tokens the model reads at most
SHARE = 0.8         # of them the surface may fill
DAYS = 30           # talking days it keeps
SLICE = 3000        # tokens of it that what reads a fixed slice reads
GIVE_UP = 600.0     # seconds after a failed summary before another try
SUMMARY = 8000      # characters of a summary
CARD = 8000         # characters of a Character Card
FIRST = CARD        # (its name before 0.7)


def bounds(recent: float, floor: int = FLOOR, cap: int = CAP, window: int = WINDOW) -> tuple[int, int]:
    """What the surface keeps and what it may reach, given the tokens of its last talking days."""
    top = min(cap, int(window * SHARE))
    keep = min(max(floor, int(recent)), top * 2 // 3)
    return keep, min(2 * keep, top)


def _in_order(exchanges: list) -> list:
    """Exchanges in the order they were said."""
    return sorted(exchanges, key=lambda item: (item.at, item.id))


@dataclass(frozen=True)
class View:
    """The surface as it stands: its messages for a model, oldest first, how many tokens its turns come to, what it
    keeps and may reach, and `upto`, when the newest of it from the host's chat was said: a host adds what came after.
    """
    messages: list
    tokens: int
    keep: int
    top: int
    upto: float


@dataclass(frozen=True)
class Card:
    """A Character Card: `by_command` when it was set (`set_card`), not only the first thing said; `on` when the host puts
    it in its system prompt."""
    text: str
    at: float
    by_command: bool
    on: bool

    @property
    def send(self) -> bool:
        """`on`, by its name before 0.7."""
        return self.on


First = Card  # (its name before 0.7)


class Surface(Speaks, Resolves):
    def __init__(self, store: Store, space: str, episodes, *, days: int = DAYS, floor: int = FLOOR, cap: int = CAP,
                 window: int = WINDOW, companion_name: str = "", display_language: str | Words = "en",
                 prompts: dict | None = None, people: People | None = None, complete=None,
                 clock: Callable[[], float] = time.time):
        self.store, self.space, self.episodes, self.people, self.complete = store, space, episodes, people, complete
        self.span, self.floor, self.cap, self.window = max(1, days), floor, cap, window
        self.companion_name, self.prompts, self.clock = companion_name, prompts or PROMPTS, clock
        self.words = Words.of(display_language)
        self.rest = providers.Rest(GIVE_UP)  # after a summary failed: a long surface is resent whole by each try

    # ---- reading ---------------------------------------------------------------------------------
    def _row(self, subject: str):
        return self.store.row("select start_id, cleared_at, summary from surfaces where space = ? and subject = ?",
                              (self.space, subject))

    def _start(self, subject: str) -> int:
        row = self._row(subject)
        return row["start_id"] if row else 0

    def began(self, subject: str) -> float:
        """When it was last cleared or shortened: 0 until then."""
        row = self._row(self.who(subject))
        return row["cleared_at"] if row else 0.0

    def _bounds(self, subject: str, start: int) -> tuple[int, int]:
        return bounds(self.episodes.tokens_after(subject, start, days=self.span), self.floor, self.cap, self.window)

    def _hers(self, who: str) -> bool:
        """Whether a line is the companion's: by her name, or as a chat message's role (`exchange.as_lines`)."""
        return who in (self.companion_name, "assistant")

    def turns(self, episode) -> list[dict]:
        """An exchange as chat messages: the companion's own lines are hers. Anyone else's are the other side's, named
        when there are several of them: a group, or a classmate she heard."""
        others = {who for who, _ in episode.lines if not self._hers(who)}
        return [{"role": "assistant", "content": said} if self._hers(who) else
                {"role": "user", "content": f"{who}: {said}" if len(others) > 1 and who else said}
                for who, said in episode.lines]

    def read(self, subject: str, *, user_name: str | None = None, here: str = "") -> View:
        """What goes in front of a new message, in any conversation with this person: what stands for the older part,
        and at most `top` tokens of the newest turns (always the newest exchange), whole exchanges, in the order they
        were said. `here` is the chat it goes into: what was left unanswered there stays the host's to show, whatever
        was said in another chat since. A Character Card is not in it: it goes in the system prompt (`card`)."""
        subject = self.who(subject)
        row = self._row(subject)
        start = row["start_id"] if row else 0
        keep, top = self._bounds(subject, start)
        kept = self.episodes.after(subject, start, top)
        head = []
        if row and row["summary"]:
            head.append({"role": "user", "content": say(self.words, "surface.summary", who=user_name or subject,
                                                        summary=row["summary"])})
        return View(head + [message for item in _in_order(kept) for message in self.turns(item)],
                    int(sum(item.tokens for item in kept)), keep, top,
                    max((item.at for item in kept if not here or item.conversation == texts.clip(here, 200)), default=0.0))

    def slice(self, subject: str, tokens: int = SLICE) -> list[dict]:
        """The newest `tokens` of it as chat messages (always the newest exchange): the same on any host, for what must
        not depend on one."""
        subject = self.who(subject)
        kept = self.episodes.after(subject, self._start(subject), tokens)
        return [message for item in _in_order(kept) for message in self.turns(item)]

    # ---- letting go ------------------------------------------------------------------------------
    async def alet_go(self, subject: str, *, user_name: str | None = None, complete=None) -> bool:
        """If it has reached its top, the older part becomes a summary and it holds `keep` tokens again, and True.
        Their words stay in deep memory. For a host that sends the surface; one that compacts its own never calls
        this. With no model (`complete`, or the one given at start), or a failing one, nothing changes: `read` still
        stops at the top, and it tries again after GIVE_UP seconds. An erase, a clear or a link while the model writes
        leaves it as they left it."""
        subject, complete = self.who(subject), complete or self.complete
        row = self._row(subject)
        start = row["start_id"] if row else 0
        keep, top = self._bounds(subject, start)
        if complete is None or not self.rest.up() or self.episodes.tokens_after(subject, start) < top:
            return False
        staying = self.episodes.after(subject, start, keep)
        leaving = self.episodes.after(subject, start, before=staying[-1].id) if staying else []
        if not leaving:
            return False
        earlier = fill(self.prompts["surface_earlier"], summary=row["summary"]) if row and row["summary"] else ""
        turns = "\n".join(f"{who}: {said}" for item in _in_order(leaving) for who, said in item.lines)
        system = fill(self.prompts["surface_summary"], user=user_name or subject, name=self.companion_name,
                      earlier=earlier, lang=say(self.words, "reflect.language"), turns=turns)
        try:
            summary = (await providers.ask(complete, system, self.prompts["surface_now"])).strip()
        except Exception as error:
            self.rest.failed(error)
            return False
        if not summary:
            self.rest.failed(ValueError("the summary came back empty"))
            return False
        first = staying[-1]
        with self.writing(subject) as person:
            found = self.episodes.get(first.id)
            if person != subject or found is None or found.subject != subject or self._start(subject) != start:
                return False
            self._put(subject, leaving[0].id, first.at, texts.fit(summary, SUMMARY))
        return True

    def _put(self, subject: str, start_id: int, cleared_at: float, summary: str) -> None:
        self.store.execute("insert into surfaces (space, subject, start_id, cleared_at, summary) values (?, ?, ?, ?, "
                           "?) on conflict(space, subject) do update set start_id = excluded.start_id, cleared_at = "
                           "excluded.cleared_at, summary = excluded.summary",
                           (self.space, subject, start_id, cleared_at, summary))

    def _combine(self, subject: str, one: tuple, other: tuple) -> None:
        """One surface for `subject` out of two (start_id, cleared_at, summary): from the lower start, with both
        summaries (one that holds the other is enough). None left to keep, no row."""
        start, cleared = min(one[0], other[0]), min(one[1], other[1])
        summary = one[2] if other[2] in one[2] else other[2] if one[2] in other[2] else f"{one[2]}\n\n{other[2]}"
        if start or summary:
            self._put(subject, start, cleared, texts.fit(summary, SUMMARY))
        else:
            self.store.execute("delete from surfaces where space = ? and subject = ?", (self.space, subject))

    def clear(self, subject: str) -> None:
        """It starts empty from now on. Deep memory, and the Character Card, stay."""
        with self.writing(subject) as subject:
            last, said = self.episodes.latest(subject)
            self._put(subject, last, math.nextafter(max(said, self.clock()), math.inf), "")

    # ---- the Character Card ----------------------------------------------------------------------
    def card(self, subject: str) -> Card | None:
        """The Character Card kept of `subject`, on or not; None when there is none."""
        row = self.store.row("select * from first_prompts where space = ? and subject = ? and text != ''",
                             (self.space, self.who(subject)))
        return Card(row["text"], row["at"], bool(row["by_command"]), bool(row["send"])) if row else None

    def noticed(self, subject: str, lines) -> None:
        """What was said to the companion, as `(who, said)` lines: the first time, a copy of the first line not hers
        stays."""
        said = next((said for who, said in lines if not self._hers(who)), "")
        text = texts.fit(texts.clean(said).strip(), CARD)
        if text:
            with self.writing(subject) as subject:
                self.store.execute("insert or ignore into first_prompts (space, subject, text, at, by_command, send) "
                                   "values (?, ?, ?, ?, 0, 0)", (self.space, subject, text, self.clock()))

    def set_card(self, subject: str, text: str) -> Card:
        """The Character Card is `text` from now on. Whether it is on stays as it was."""
        text = texts.fit(texts.clean(texts.required(text, "a Character Card")).strip(), CARD)
        with self.writing(subject) as subject:
            self.store.execute("insert into first_prompts (space, subject, text, at, by_command, send) values (?, ?, "
                               "?, ?, 1, 0) on conflict(space, subject) do update set text = excluded.text, at = "
                               "excluded.at, by_command = 1", (self.space, subject, text, self.clock()))
        return self.card(subject)

    def card_on(self, subject: str, on: bool = True) -> bool:
        """Whether the host puts it in its system prompt; False when there is none."""
        with self.writing(subject) as subject:
            return self.store.execute("update first_prompts set send = ? where space = ? and subject = ? and text "
                                      "!= ''", (int(bool(on)), self.space, subject)).rowcount > 0

    def drop_card(self, subject: str) -> bool:
        """There is none from now on: its row stays with no text, so the next message does not become it."""
        with self.writing(subject) as subject:
            return self.store.execute("update first_prompts set text = '', by_command = 0, send = 0 where space = ? "
                                      "and subject = ? and text != ''", (self.space, subject)).rowcount > 0

    # (their names before 0.7)
    first, set_first, send_first, drop_first = card, set_card, card_on, drop_card

    # ---- keeping up ------------------------------------------------------------------------------
    def subjects(self) -> list[str]:
        """Everyone a surface or a Character Card is kept of."""
        return [row["subject"] for row in self.store.rows(
            "select subject from surfaces where space = ? union select subject from first_prompts where space = ? "
            "order by subject", (self.space, self.space))]

    def erase(self, subject: str) -> None:
        with self.writing(subject) as subject:
            for table in ("surfaces", "first_prompts"):
                self.store.execute(f"delete from {table} where space = ? and subject = ?", (self.space, subject))

    def join(self, old: str, new: str) -> None:
        """`old` is the person `new` now: their surfaces are one, from the lower start (none counts as 0, all of it),
        with both summaries; their own Character Card stays, or `old`'s when they have none. Before the exchanges move:
        an account that holds nothing changes nothing."""
        with self.store.transaction():
            theirs = self._row(old)
            if theirs is not None or self.episodes.holds(old):
                mine = self._row(new)
                self._combine(new, tuple(theirs) if theirs else (0, 0.0, ""), tuple(mine) if mine else (0, 0.0, ""))
            self.store.execute("delete from surfaces where space = ? and subject = ?", (self.space, old))
            self.store.execute("update or ignore first_prompts set subject = ? where space = ? and subject = ?",
                               (new, self.space, old))
            self.store.execute("delete from first_prompts where space = ? and subject = ?", (self.space, old))

    def export_rows(self) -> dict:
        """Ids mean nothing in another file, so a surface goes by the time it starts."""
        return {"surfaces": [dict(row) for row in self.store.rows(
                    "select subject, cleared_at, summary from surfaces where space = ?", (self.space,))],
                "first_prompts": [dict(row) for row in self.store.rows(
                    "select subject, text, at, by_command, send from first_prompts where space = ?", (self.space,))]}

    def import_rows(self, surfaces, firsts) -> None:
        """Add what an export kept, held to the rules of writing, after its exchanges: a surface starts at the last
        exchange said before its `cleared_at`, and joins one that is here as `join` does; a Character Card that is here
        stays."""
        with self.store.transaction():
            for row in surfaces:
                cleared = dates.seconds(row.get("cleared_at")) if isinstance(row, dict) else None
                subject, summary = (row.get("subject"), row.get("summary")) if isinstance(row, dict) else (None, None)
                if isinstance(subject, str) and subject.strip() and isinstance(summary, str) and cleared is not None:
                    subject = self.who(subject)
                    mine = self._row(subject)
                    given = self.episodes.latest(subject, cleared)[0], cleared, texts.fit(texts.clean(summary), SUMMARY)
                    if mine is None:
                        self._put(subject, *given)
                    else:
                        self._combine(subject, tuple(mine), given)
            for row in firsts:
                at = dates.seconds(row.get("at")) if isinstance(row, dict) else None
                subject, text = (row.get("subject"), row.get("text")) if isinstance(row, dict) else (None, None)
                if isinstance(subject, str) and subject.strip() and isinstance(text, str) and at is not None:
                    self.store.execute("insert or ignore into first_prompts (space, subject, text, at, by_command, "
                                       "send) values (?, ?, ?, ?, ?, ?)",
                                       (self.space, self.who(subject), texts.fit(texts.clean(text).strip(), FIRST), at,
                                        int(bool(row.get("by_command"))), int(bool(row.get("send")))))
