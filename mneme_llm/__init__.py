"""mneme-llm: memory and mood for AI companions, kept in one SQLite file that any model, and any project, can use.

    from mneme_llm import Mneme
    m = Mneme("companion.db", space="dafeiyu", lang="zh", name="大肥鱼", complete=my_model)
    m.remember("discord:42", "养了一只叫年糕的猫", kind="fact", key="pet.name", importance=4)
    system_prompt += await m.aprompt("discord:42", query=user_message, user="Leo")
    await m.aobserve("discord:42", [("Leo", user_message), ("大肥鱼", reply)], user="Leo")

Swap the model behind your app and point it at the same file: the facts, the history and the mood carry over.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Callable

from . import dates, exchange as exchanges, providers
from .capture import WORTH, notes_in, reflect_prompt, writer_prompt
from .decide import Answer, Chain, Choice, Luna, Predicate, Prompt, Score
from .i18n import say
from .meaning import Embeddings, Meaning, OpenAIEmbeddings, ledger
from .memory import KINDS, Memory, Note, Recall
from .mood import Emotion, Mood, MoodEvent, MoodSettings
from .providers import Unavailable, run
from .store import SCHEMA_VERSION, Store

__version__ = "0.1.0"


def _optional(module: str, name: str):
    """A removable tier's class, or None when its file was deleted from this install."""
    try:
        return getattr(__import__(f"mneme_llm.{module}", fromlist=[name]), name)
    except ImportError:
        return None


@dataclass(frozen=True)
class Observation:
    """What `observe` made of one exchange: the mood change (None when nothing moved) and the notes kept."""
    mood: MoodEvent | None = None
    notes: list = field(default_factory=list)
    worth: float | None = None  # how likely the exchange held something worth remembering, when it was asked
    error: str = ""             # why notes could not be written (the note writer failed), if they could not


class Mneme:
    """Memory, mood, and the decision and meaning tiers of one space, in one object.

    name           the companion's own name (the person's is given per call, as `user`)
    complete       your own chat model, `complete(system, user) -> str` (sync or async). It is the last tier of
                   decisions and of meaning, and it writes notes (`observe`, `capture`) and the profile card
                   (`reflect`). It can be a fixed, cheap model whatever model your conversation uses.
    luna, micro    decision tiers 1 and 2: True uses GPT-6 Luna's Decisions API when OPENAI_API_KEY is set (it
                   falls through without one) and keeps the local micro model; False leaves either out; or pass
                   a tier of your own.
    embed          meaning tier 1: True uses OpenAI embeddings when OPENAI_API_KEY is set; or pass any embedder
                   (`Embeddings(fn, name=...)` for your own function); False leaves it out.
    meaning_micro  meaning tier 2: word centroids learned from tier 1 (False leaves it out).
    language       meaning tier 3: the language notes are unified into, "English" by default; None turns it off.
    """

    def __init__(self, path: str = "mneme.db", space: str = "default", *, lang: str = "en",
                 name: str = "the assistant", zone: tzinfo | None = None, complete=None, luna=True, micro=True,
                 embed=True, meaning_micro=True, language: str | None = "English",
                 mood: MoodSettings = MoodSettings(), half_life_days: float = 30.0, daily_quota: int = 8,
                 clock: Callable[[], float] = time.time):
        self.store = Store(path)
        ledger.repair(self.store)  # centroids changed by something that kept no account start over
        self.space, self.lang, self.name, self.complete = space, lang, name, complete
        self._tiers = [Luna() if luna is True else luna] if luna else []
        Micro = _optional("decide.micro", "Micro") if micro is True else None
        self.micro = (Micro(self.store) if Micro is not None else None) if micro is True else micro or None
        self._tiers += [self.micro] if self.micro is not None else []
        self.decider = self._chain(complete)
        self.meaning = self._meaning(embed, meaning_micro, language, complete)
        self.memory = Memory(self.store, space, half_life_days=half_life_days, daily_quota=daily_quota, zone=zone,
                             lang=lang, meaning=self.meaning, clock=clock)
        self.mood = Mood(self.store, space, decider=self.decider, settings=mood, name=name, lang=lang, clock=clock)

    def _chain(self, complete) -> Chain:
        return Chain(*self._tiers, Prompt(complete) if complete is not None else None)

    def _meaning(self, embed, meaning_micro, language, complete) -> Meaning | None:
        embedder = None
        if embed is True:
            embedder = OpenAIEmbeddings()
        elif callable(embed) and not hasattr(embed, "embed"):
            embedder = Embeddings(embed, name=f"custom:{getattr(embed, '__qualname__', 'function')}")
        elif embed:
            embedder = embed
        centroids = None
        if embedder is not None and meaning_micro:  # they are learned from tier 1's vectors
            TermCentroids = _optional("meaning.micro", "TermCentroids") if meaning_micro is True else None
            centroids = meaning_micro if meaning_micro is not True else \
                TermCentroids(self.store, embedder.name) if TermCentroids is not None else None
        Unify = _optional("meaning.unify", "Unify") if language else None
        unify = Unify(complete, language) if Unify is not None else None
        if embedder is None and centroids is None and unify is None:
            return None
        return Meaning(self.store, embedder, centroids, unify)

    def _decider(self, complete) -> Chain:
        """The chain for one call: with a `complete` of the call's own as its last tier."""
        if complete is None:
            return self.decider
        decider = self._chain(complete)
        decider.stats = self.decider.stats  # one report for both
        return decider

    # ---- the few calls most programs need ------------------------------------------------------------
    def remember(self, subject: str, text: str, *, kind: str | None = None, key: str | None = None,
                 importance: int = 2, feeling: float = 0.0, happened_at: float | None = None,
                 source: str | None = None, gloss: str | None = None) -> Note | None:
        """Keep a note (see `Memory.remember`)."""
        return self.memory.remember(subject, text, kind=kind, key=key, importance=importance, feeling=feeling,
                                    happened_at=happened_at, source=source, gloss=gloss)

    def recall(self, subject: str, query: str, *, limit: int = 6, budget: int = 800, important: int = 2,
               recent: int = 1, log: bool = True) -> Recall:
        """Word matching only, no network; `arecall` adds the meaning tiers."""
        return self.memory.recall(subject, query, limit=limit, budget=budget, important=important, recent=recent,
                                  log=log)

    async def arecall(self, subject: str, query: str, *, limit: int = 6, budget: int = 800, important: int = 2,
                      recent: int = 1, log: bool = True, complete=None) -> Recall:
        return await self.memory.arecall(subject, query, limit=limit, budget=budget, important=important,
                                         recent=recent, log=log, complete=complete)

    def forget(self, subject: str, *, id: int | None = None, key: str | None = None) -> int:
        """Hide a note (by id) or a key's live note; it stays in the history until `purge`."""
        return self.memory.forget(subject, id=id, key=key)

    def purge(self, subject: str | None = None) -> int:
        """Erase hidden and replaced notes for good (all subjects when none is given)."""
        return self.memory.purge(subject)

    def erase(self, subject: str) -> int:
        """Everything about a person, gone for good ("forget me"): notes, history, vectors, what they taught the
        word centroids, profile card, recall log, mood and its timeline. Returns how many notes there were."""
        with self.store.transaction():
            count = self.memory.erase(subject)
            self.mood.reset(subject)
        return count

    def prompt(self, subject: str, query: str = "", *, user: str | None = None, mark: bool = True, limit: int = 6,
               budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None) -> str:
        """What to add to the system prompt this turn (word matching only): notes for `query`, and the mood's
        news, told once. `user` is how the notes' header names the person; the rest is as in `Memory.context`."""
        notes = self.memory.context(subject, query, user=user, limit=limit, budget=budget, important=important,
                                    recent=recent, header=header)
        return "\n\n".join(part for part in (notes, self.mood.news(subject, mark=mark) or "") if part)

    async def aprompt(self, subject: str, query: str = "", *, user: str | None = None, mark: bool = True,
                      limit: int = 6, budget: int = 800, important: int = 2, recent: int = 1,
                      header: str | None = None, complete=None) -> str:
        """`prompt` with the meaning tiers."""
        notes = await self.memory.acontext(subject, query, user=user, limit=limit, budget=budget, important=important,
                                           recent=recent, header=header, complete=complete)
        return "\n\n".join(part for part in (notes, self.mood.news(subject, mark=mark) or "") if part)

    async def aobserve(self, subject: str, exchange, *, source: str = "user", user: str = "the user",
                       complete=None, mood: bool = True, capture: bool = True, gate: float = 0.5) -> Observation:
        """Call after each exchange, once the reply is out: judges the mood and keeps what is worth remembering.

        One decision request answers both the mood questions and "worth remembering?", so the note writer is
        only called when there is something to write. Notes are only taken from exchanges the person started
        (`source="user"`). `complete` gives this call a chat model in place of the one given at start. If the
        note writer fails, the mood is still applied and the failure is in `Observation.error`.
        """
        exchange = exchanges.as_text(exchange)  # once (it may be a generator); a wrong one is the caller's mistake
        writer = complete or self.complete
        decider = self._decider(complete)
        judge_mood = mood and source not in self.mood.settings.skip
        keep_notes = capture and source == "user" and writer is not None
        questions = (self.mood.questions() if judge_mood else []) + ([WORTH] if keep_notes else [])
        answers = {}
        if questions and decider.tiers:
            answers = await decider.adecide(exchanges.frame(exchange, source=source, user=user, assistant=self.name),
                                            questions)
        event = self.mood.apply_answers(subject, answers, exchange, source=source, user=user) if judge_mood else None
        notes, worth, error = [], answers.get(WORTH.name), ""
        if keep_notes:
            try:
                notes = await self._capture(subject, exchange, user, worth, gate, writer)
            except Exception as failure:  # the note writer is the host's model: report it, keep the mood
                error = f"{type(failure).__name__}: {failure}"[:300]
        return Observation(event, notes, worth.probability if worth is not None else None, error)

    def observe(self, subject: str, exchange, **options) -> Observation:
        """`aobserve` for code without an event loop."""
        return run(self.aobserve(subject, exchange, **options))

    async def acapture(self, subject: str, exchange, *, user: str = "the user", gate: float = 0.5,
                       complete=None) -> list[Note]:
        """Notes kept from one exchange, without judging the mood (source "auto", so the daily quota applies).
        `WORTH` is asked first when a decision tier is there; the note writer only when it says yes."""
        worth = None
        decider = self._decider(complete)
        if decider.tiers and gate > 0:
            framed = exchanges.frame(exchange, source="user", user=user, assistant=self.name)
            worth = (await decider.adecide(framed, [WORTH])).get(WORTH.name)
        return await self._capture(subject, exchange, user, worth, gate, complete or self.complete)

    def capture(self, subject: str, exchange, **options) -> list[Note]:
        """`acapture` for code without an event loop."""
        return run(self.acapture(subject, exchange, **options))

    async def _capture(self, subject: str, exchange, user: str, worth: Answer | None, gate: float,
                       complete) -> list[Note]:
        if worth is not None and worth.probability < gate:
            return []
        exchange = exchanges.as_text(exchange)
        memory = self.memory
        known = [item.note.text for item in memory.recall(subject, exchange, log=False).chosen]
        unify = self.meaning.unify if self.meaning is not None else None
        today = dates.local(memory.clock(), memory.zone).strftime("%Y-%m-%d (%A)")
        reply = await providers.ask(complete, writer_prompt(user, known, today, unify.language if unify else None),
                                    exchange)
        kept = []
        for fields in notes_in(reply, memory.clock(), memory.zone):
            note = memory.remember(subject, source="auto", **fields)
            if note is not None:
                kept.append(note)
        if kept and self.meaning is not None:
            await self.meaning.prepare_vectors(kept)  # embed now, after the reply, rather than at the next recall
        return kept

    async def areflect(self, subject: str, *, user: str = "the user", limit: int = 60, complete=None) -> str | None:
        """Rewrite the person's profile card from their most important and newest notes (once a day is plenty);
        returns the new card."""
        notes = sorted(self.memory.notes(subject), key=lambda note: (-note.importance, -note.id))[:limit]
        if not notes:
            return None
        system = reflect_prompt(user, self.name, say(self.lang, "reflect.language"), notes)
        card = (await providers.ask(complete or self.complete, system, "Write the impression now.")).strip()
        if card:
            self.memory.set_profile(subject, card)
        return card or None

    def reflect(self, subject: str, **options) -> str | None:
        """`areflect` for code without an event loop."""
        return run(self.areflect(subject, **options))

    def report(self) -> dict:
        """What each tier has answered, abstained on or failed, and what the paid ones cost."""
        return {"decisions": self.decider.report(), "meaning": self.meaning.report() if self.meaning else None}

    # ---- moving between projects ------------------------------------------------------------------
    def export_data(self) -> dict:
        """This space as plain JSON (see docs/FORMAT.md)."""
        return {"mneme_llm": SCHEMA_VERSION, "space": self.space, "exported_at": time.time(),
                **self.memory.export_rows(), **self.mood.export_rows()}

    def import_data(self, data: dict) -> int:
        """Add an export to this space, held to the rules of writing; returns how many notes were added."""
        if not isinstance(data, dict):
            raise TypeError("an export is a JSON object")
        rows = {name: data.get(name) if isinstance(data.get(name), list) else []
                for name in ("memories", "profiles", "moods", "mood_events")}
        with self.store.transaction():
            added = self.memory.import_rows(rows["memories"], rows["profiles"])
            self.mood.import_rows(rows["moods"], rows["mood_events"])
        return added

    def close(self) -> None:
        flush = getattr(self.micro, "flush", None)  # (a host's own tier may keep nothing)
        if flush is not None:
            flush()
        self.store.close()

    def __enter__(self) -> "Mneme":
        return self

    def __exit__(self, *_) -> None:
        self.close()


__all__ = ["Answer", "Chain", "Choice", "Embeddings", "Emotion", "KINDS", "Luna", "Meaning", "Memory", "Mneme",
           "Mood", "MoodEvent", "MoodSettings", "Note", "Observation", "OpenAIEmbeddings", "Predicate", "Prompt",
           "Recall", "Score", "Store", "Unavailable", "__version__"]
