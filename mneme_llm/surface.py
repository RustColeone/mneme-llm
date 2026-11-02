"""The surface: what was said lately, as real turns, in front of the deep memory that holds every word.

Everything said is kept word for word the moment it is said (`episodes.py`): that is deep memory, and compaction never
touches it. The surface is not a second store but a window on its newest part. A host that has a context of its own
keeps it and compacts it itself, since whoever sends the context compacts it, and this stays a copy for what must read
the same on any host; a host with none sends `read`, and lets `alet_go` shorten it.

How much it keeps counts talking days, as fading does (`dates.talking_day`). It keeps what the last `days` talking days
hold, but never less than `floor` tokens, so six messages a day are not summarised after a month. Nothing leaves until
it holds twice that; then the older part becomes one summary, its words still in deep memory. `cap` is the top whatever
the rest says, or 80% of `window` on a smaller model:

    keep = min(max(floor, last days), 2/3 cap)      top = min(2 keep, cap)

A person's first prompt is kept here too: the first thing they said, usually who they want the companion to be. A
conversation can lose it, so a copy stays out of the conversation, where it does not fade. The person can set it
(`set_first`), and it goes in with the first push of a new conversation only if they ask (`send_first`), since they
may have grown away from it. The surface follows the person; a host can ask for one `conversation`.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from . import dates, providers, text as texts
from .decide import fit
from .episodes import Episode
from .i18n import Speaks, Words, fill, say
from .people import People, Resolves
from .prompts import PROMPTS
from .store import Store

FLOOR = 70_000      # tokens it never keeps less than
CAP = 504_000       # tokens it never holds more than
WINDOW = 1_048_576  # tokens the model reads at most
SHARE = 0.8         # of them the surface may fill
DAYS = 30           # talking days it keeps
EXCHANGE = 2.4      # tokens two messages cost beyond their words
SLICE = 3000        # tokens of it that what reads a fixed slice reads
SUMMARY = 8000      # characters of a summary
FIRST = 8000        # characters of a first prompt


def bounds(recent: float, floor: int = FLOOR, cap: int = CAP, window: int = WINDOW) -> tuple[int, int]:
    """What the surface keeps and what it may reach, given the tokens of its last talking days."""
    top = min(cap, int(window * SHARE))
    keep = min(max(floor, int(recent)), top * 2 // 3)
    return keep, min(2 * keep, top)


@dataclass(frozen=True)
class View:
    """The surface as it stands: its turns as chat messages, what stands for the older part, and its size."""
    messages: list
    summary: str
    tokens: int
    keep: int
    top: int


@dataclass(frozen=True)
class First:
    """A person's first prompt: `by_command` when they set it themselves, `send` when it goes in with a first push."""
    text: str
    at: float
    by_command: bool
    send: bool


class Surface(Speaks, Resolves):
    def __init__(self, store: Store, space: str, episodes, *, days: int = DAYS, floor: int = FLOOR, cap: int = CAP,
                 window: int = WINDOW, companion_name: str = "", display_language: str | Words = "en",
                 prompts: dict | None = None, people: People | None = None, complete=None,
                 clock: Callable[[], float] = time.time):
        self.store, self.space, self.episodes, self.people, self.complete = store, space, episodes, people, complete
        self.span, self.floor, self.cap, self.window = days, floor, cap, window
        self.companion_name, self.prompts, self.clock = companion_name, prompts or PROMPTS, clock
        self.words = Words.of(display_language)

    # ---- reading ---------------------------------------------------------------------------------
    def _row(self, subject: str):
        return self.store.row("select since, summary from surfaces where space = ? and subject = ?",
                              (self.space, subject))

    def began(self, subject: str) -> float:
        """When it starts: 0 until it has let something go or been cleared."""
        row = self._row(self.who(subject))
        return row["since"] if row else 0.0

    def empty(self, subject: str) -> bool:
        subject = self.who(subject)
        return self.store.row("select 1 from episodes where space = ? and subject = ? and at >= ? limit 1",
                              (self.space, subject, self.began(subject))) is None

    def _held(self, subject: str, conversation: str) -> list:
        """The exchanges in it, oldest first, with what each costs."""
        row = self._row(subject)
        where = "space = ? and subject = ? and at >= ?" + (" and conversation = ?" if conversation else "")
        values = (self.space, subject, row["since"] if row else 0.0) + ((conversation,) if conversation else ())
        found = [Episode.of(item) for item in self.store.rows(
            f"select * from episodes where {where} order by at, id", values)]
        return [(item, texts.tokens(item.text) + EXCHANGE) for item in found]

    def _bounds(self, subject: str, held: list) -> tuple[int, int]:
        days = self.episodes.talking_days(subject)
        edge = days[-self.span] if len(days) >= self.span else (days[0] if days else 0)
        recent = sum(cost for item, cost in held if self.episodes.day_of(item.at) >= edge)
        return bounds(recent, self.floor, self.cap, self.window)

    def turns(self, episode) -> list[dict]:
        """An exchange as chat messages. Its lines by the companion are hers; with none named so, the last line is, as
        an exchange is what the person said and the reply. A line of someone else in a group keeps its name."""
        lines = episode.lines
        named = {who for who, _ in lines if who == self.companion_name}
        reply = len(lines) - 1 if not named and len(lines) > 1 else -1
        speakers = {who for number, (who, _) in enumerate(lines) if who not in named and number != reply}
        found = []
        for number, (who, said) in enumerate(lines):
            if who in named or number == reply:
                found.append({"role": "assistant", "content": said})
            else:
                found.append({"role": "user", "content": f"{who}: {said}" if len(speakers) > 1 and who else said})
        return found

    def read(self, subject: str, *, conversation: str = "") -> View:
        """The surface now: at most `top` tokens of the newest turns, whole exchanges, in the order they were said."""
        subject = self.who(subject)
        held = self._held(subject, conversation)
        keep, top = self._bounds(subject, held)
        kept, used = [], 0.0
        for item, cost in reversed(held):
            if used + cost > top:
                break
            kept.append(item)
            used += cost
        row = self._row(subject)
        return View([message for item in reversed(kept) for message in self.turns(item)],
                    row["summary"] if row else "", int(used), keep, top)

    def slice(self, subject: str, tokens: int = SLICE, *, conversation: str = "") -> list[dict]:
        """The newest `tokens` of it as chat messages: the same on any host, for what must not depend on one."""
        kept, used = [], 0.0
        for item, cost in reversed(self._held(self.who(subject), conversation)):
            if used + cost > tokens:
                break
            kept.append(item)
            used += cost
        return [message for item in reversed(kept) for message in self.turns(item)]

    def push(self, subject: str, *, user_name: str | None = None, conversation: str = "") -> list[dict]:
        """What goes into a new conversation that starts with nothing, once: their first prompt if they asked for it,
        what stands for the older part, and the surface. Not after a person cleared it, as it is empty then."""
        subject = self.who(subject)
        view, first = self.read(subject, conversation=conversation), self.first(subject)
        head = [{"role": "user", "content": first.text}] if first and first.send else []
        if view.summary:
            head.append({"role": "user", "content": say(self.words, "surface.summary", who=user_name or subject,
                                                        summary=view.summary)})
        return head + view.messages

    # ---- letting go ------------------------------------------------------------------------------
    async def alet_go(self, subject: str, *, user_name: str | None = None, complete=None,
                      conversation: str = "") -> bool:
        """If it has reached its top, the older part becomes a summary and it holds `keep` tokens again, and True.
        Their words stay in deep memory. For a host that sends the surface; one that compacts its own never calls
        this. With no model (`complete`, or the one given at start), or a failing one, nothing changes: `read` still
        stops at the top, and the next call tries again."""
        subject, complete = self.who(subject), complete or self.complete
        held = self._held(subject, conversation)
        keep, top = self._bounds(subject, held)
        if sum(cost for _, cost in held) < top or complete is None:
            return False
        staying, used = len(held), 0.0
        while staying and used + held[staying - 1][1] <= keep:
            staying -= 1
            used += held[staying][1]
        if not staying or staying == len(held):
            return False
        row = self._row(subject)
        earlier = f"\n\nWhat was kept of what came before:\n{row['summary']}" if row and row["summary"] else ""
        leaving = "\n".join(f"{who}: {said}" for item, _ in held[:staying] for who, said in item.lines)
        system = fill(self.prompts["surface_summary"], user=user_name or subject, name=self.companion_name,
                      earlier=earlier, lang=say(self.words, "reflect.language"), turns=leaving)
        try:
            summary = (await providers.ask(complete, system, "Write the summary now.")).strip()
        except Exception:
            return False
        if not summary:
            return False
        self._put(subject, held[staying][0].at, fit(summary, SUMMARY))
        return True

    def let_go(self, subject: str, **options) -> bool:
        return providers.run(self.alet_go(subject, **options))

    def _put(self, subject: str, since: float, summary: str) -> None:
        self.store.execute("insert into surfaces (space, subject, since, summary, updated_at) values (?, ?, ?, ?, ?) "
                           "on conflict(space, subject) do update set since = excluded.since, summary = "
                           "excluded.summary, updated_at = excluded.updated_at",
                           (self.space, subject, since, summary, self.clock()))

    def clear(self, subject: str) -> None:
        """It starts empty from now on. Deep memory, and the first prompt, stay."""
        with self.writing(subject) as subject:
            latest = self.store.row("select max(at) as at from episodes where space = ? and subject = ?",
                                    (self.space, subject))["at"]
            self._put(subject, math.nextafter(max(latest or 0.0, self.clock()), math.inf), "")

    # ---- the first prompt ------------------------------------------------------------------------
    def first(self, subject: str) -> First | None:
        row = self.store.row("select * from first_prompts where space = ? and subject = ?",
                             (self.space, self.who(subject)))
        return First(row["text"], row["at"], bool(row["by_command"]), bool(row["send"])) if row else None

    def noticed(self, subject: str, said: str) -> None:
        """What a person said to the companion: the first time, a copy of it stays."""
        text = fit(texts.clean(said).strip(), FIRST)
        if text:
            with self.writing(subject) as subject:
                self.store.execute("insert or ignore into first_prompts (space, subject, text, at, by_command, send) "
                                   "values (?, ?, ?, ?, 0, 0)", (self.space, subject, text, self.clock()))

    def set_first(self, subject: str, text: str) -> First:
        """The person's first prompt is `text` from now on, by their own word. Whether it is sent stays as it was."""
        text = fit(texts.clean(texts.required(text, "a first prompt")).strip(), FIRST)
        with self.writing(subject) as subject:
            self.store.execute("insert into first_prompts (space, subject, text, at, by_command, send) values (?, ?, "
                               "?, ?, 1, 0) on conflict(space, subject) do update set text = excluded.text, at = "
                               "excluded.at, by_command = 1", (self.space, subject, text, self.clock()))
        return self.first(subject)

    def send_first(self, subject: str, send: bool = True) -> bool:
        """Whether it goes in with a first push; False when they have none."""
        with self.writing(subject) as subject:
            return self.store.execute("update first_prompts set send = ? where space = ? and subject = ?",
                                      (int(bool(send)), self.space, subject)).rowcount > 0

    def drop_first(self, subject: str) -> bool:
        with self.writing(subject) as subject:
            return self.store.execute("delete from first_prompts where space = ? and subject = ?",
                                      (self.space, subject)).rowcount > 0

    # ---- keeping up ------------------------------------------------------------------------------
    def erase(self, subject: str) -> None:
        with self.writing(subject) as subject:
            for table in ("surfaces", "first_prompts"):
                self.store.execute(f"delete from {table} where space = ? and subject = ?", (self.space, subject))

    def join(self, old: str, new: str) -> None:
        """`old` is the person `new` now: their own summary and first prompt stay, or `old`'s when they have none."""
        with self.store.transaction():
            for table in ("surfaces", "first_prompts"):
                self.store.execute(f"update or ignore {table} set subject = ? where space = ? and subject = ?",
                                   (new, self.space, old))
                self.store.execute(f"delete from {table} where space = ? and subject = ?", (self.space, old))

    def export_rows(self) -> dict:
        return {"surfaces": [dict(row) for row in self.store.rows(
                    "select subject, since, summary, updated_at from surfaces where space = ?", (self.space,))],
                "first_prompts": [dict(row) for row in self.store.rows(
                    "select subject, text, at, by_command, send from first_prompts where space = ?", (self.space,))]}

    def import_rows(self, surfaces, firsts) -> None:
        """Add what an export kept, held to the rules of writing: what is here already stays."""
        with self.store.transaction():
            for row in surfaces:
                since = dates.seconds(row.get("since")) if isinstance(row, dict) else None
                subject, summary = (row.get("subject"), row.get("summary")) if isinstance(row, dict) else (None, None)
                if isinstance(subject, str) and subject.strip() and isinstance(summary, str) and since is not None:
                    self.store.execute("insert or ignore into surfaces (space, subject, since, summary, updated_at) "
                                       "values (?, ?, ?, ?, ?)", (self.space, self.who(subject), since,
                                                                  fit(texts.clean(summary), SUMMARY), self.clock()))
            for row in firsts:
                at = dates.seconds(row.get("at")) if isinstance(row, dict) else None
                subject, text = (row.get("subject"), row.get("text")) if isinstance(row, dict) else (None, None)
                if isinstance(subject, str) and subject.strip() and isinstance(text, str) and text.strip() \
                        and at is not None:
                    self.store.execute("insert or ignore into first_prompts (space, subject, text, at, by_command, "
                                       "send) values (?, ?, ?, ?, ?, ?)",
                                       (self.space, self.who(subject), fit(texts.clean(text), FIRST), at,
                                        int(bool(row.get("by_command"))), int(bool(row.get("send")))))
