"""mneme-llm: memory and mood for AI companions, kept in one SQLite file that any model, and any project, can use.

    from mneme_llm import Mneme
    m = Mneme("companion.db", space="dafeiyu", lang="zh", name="大肥鱼", complete=my_model)
    m.remember("discord:42", "养了一只叫年糕的猫", kind="fact", key="pet.name", importance=4)
    system_prompt += await m.aprompt("discord:42", query=user_message, name="Leo")
    await m.aobserve("discord:42", [("Leo", user_message), ("大肥鱼", reply)], user="Leo")

Swap the model behind your app and point it at the same file: the facts, the history and the mood carry over.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Callable

from .capture import WORTH, acapture, areflect
from .decide import Answer, Chain, Choice, Luna, Predicate, Prompt, Score, run
from .meaning import Embeddings, Meaning, OpenAIEmbeddings
from .meaning.unify import Unify
from .memory import KINDS, Memory, Note, Recall
from .mood import Emotion, Mood, MoodEvent, MoodSettings
from .store import Store

__version__ = "0.1.0"


@dataclass(frozen=True)
class Observation:
    """What `observe` made of one exchange: the mood change (None when nothing moved) and the notes kept."""
    mood: MoodEvent | None = None
    notes: list = field(default_factory=list)
    worth: float | None = None  # how likely the exchange held something worth remembering, when it was asked
    error: str = ""             # why notes could not be written (the note writer failed), if they could not


class Mneme:
    """Memory, mood, and the decision and meaning tiers of one space, in one object.

    complete       your own chat model, `complete(system, user) -> str` (sync or async). It is the last tier of
                   decisions and of meaning, and it writes notes (`observe`, `capture`) and the profile card
                   (`reflect`). It can be a fixed, cheap model whatever model your conversation uses.
    luna, micro    decision tiers 1 and 2: True uses GPT-6 Luna's Decisions API when OPENAI_API_KEY is set (it
                   falls through without one) and keeps the local micro model; False leaves either out.
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
        self.space, self.lang, self.name, self.complete = space, lang, name, complete
        tiers = []
        if luna is True:
            tiers.append(Luna())
        elif luna:
            tiers.append(luna)
        self.micro = None
        if micro:
            try:
                from .decide.micro import Micro
            except ImportError:  # the micro model was removed from this install
                Micro = None
            if Micro is not None:
                self.micro = Micro(self.store) if micro is True else micro
                tiers.append(self.micro)
        if complete is not None:
            tiers.append(Prompt(complete))
        self.decider = Chain(*tiers)
        self.meaning = self._meaning(embed, meaning_micro, language, complete)
        self.memory = Memory(self.store, space, half_life_days=half_life_days, daily_quota=daily_quota, zone=zone,
                             lang=lang, meaning=self.meaning, clock=clock)
        self.mood = Mood(self.store, space, decider=self.decider, settings=mood, name=name, lang=lang, clock=clock)

    def _meaning(self, embed, meaning_micro, language, complete) -> Meaning | None:
        embedder = None
        if embed is True:
            embedder = OpenAIEmbeddings()
        elif callable(embed) and not hasattr(embed, "embed"):
            embedder = Embeddings(embed, name=f"custom:{getattr(embed, '__qualname__', 'function')}")
        elif embed:
            embedder = embed
        centroids = None
        if embedder is not None and meaning_micro:
            try:
                from .meaning.micro import TermCentroids
            except ImportError:  # the meaning micro tier was removed from this install
                TermCentroids = None
            if TermCentroids is not None:
                centroids = TermCentroids(self.store, embedder.name) if meaning_micro is True else meaning_micro
        unify = Unify(complete, language) if language else None
        if embedder is None and centroids is None and unify is None:
            return None
        return Meaning(self.store, embedder, centroids, unify)

    def _decider(self, complete) -> Chain:
        if complete is None:
            return self.decider
        decider = Chain(*[tier for tier in self.decider.tiers if tier.name != "prompt"], Prompt(complete))
        decider.stats = self.decider.stats  # one report for both
        return decider

    # ---- the few calls most programs need ------------------------------------------------------------
    def remember(self, subject: str, text: str, **options) -> Note | None:
        return self.memory.remember(subject, text, **options)

    def recall(self, subject: str, query: str, **options) -> Recall:
        """Word matching only, no network; `arecall` adds the meaning tiers."""
        return self.memory.recall(subject, query, **options)

    async def arecall(self, subject: str, query: str, *, complete=None, **options) -> Recall:
        return await self.memory.arecall(subject, query, complete=complete, **options)

    def forget(self, subject: str, **options) -> int:
        return self.memory.forget(subject, **options)

    def prompt(self, subject: str, query: str = "", *, name: str | None = None, mark: bool = True,
               **options) -> str:
        """What to add to the system prompt this turn (word matching only): notes for `query`, and the mood's
        news, told once."""
        parts = [self.memory.context(subject, query, name=name, **options), self.mood.news(subject, mark=mark) or ""]
        return "\n\n".join(part for part in parts if part)

    async def aprompt(self, subject: str, query: str = "", *, name: str | None = None, mark: bool = True,
                      complete=None, **options) -> str:
        """`prompt` with the meaning tiers."""
        notes = await self.memory.acontext(subject, query, name=name, complete=complete, **options)
        parts = [notes, self.mood.news(subject, mark=mark) or ""]
        return "\n\n".join(part for part in parts if part)

    async def aobserve(self, subject: str, exchange, *, source: str = "user", user: str = "the user",
                       complete=None, mood: bool = True, capture: bool = True, gate: float = 0.5) -> Observation:
        """Call after each exchange, once the reply is out: judges the mood and keeps what is worth remembering.

        One decision request answers both the mood questions and "worth remembering?", so the note writer is
        only called when there is something to write. Notes are only taken from exchanges the person started
        (`source="user"`). `complete` gives this call a chat model in place of the one given at start. If the
        note writer fails, the mood is still applied and the failure is in `Observation.error`.
        """
        writer = complete or self.complete
        decider = self._decider(complete)
        judge_mood = mood and source not in self.mood.settings.skip
        keep_notes = capture and source == "user" and writer is not None
        questions = (self.mood.questions() if judge_mood else []) + ([WORTH] if keep_notes else [])
        answers = {}
        if questions and decider.tiers:
            answers = await decider.adecide(self.mood.frame(exchange, source, user), questions)
        event = self.mood.apply_answers(subject, answers, exchange, source=source, user=user) if judge_mood else None
        notes, worth, error = [], answers.get(WORTH.name), ""
        if keep_notes:
            try:
                notes = await acapture(self, subject, exchange, user=user, gate=gate if worth is not None else 0,
                                       worth=worth, complete=writer)
            except Exception as failure:  # the note writer is the host's model: report it, keep the mood
                error = f"{type(failure).__name__}: {failure}"[:300]
        return Observation(event, notes, worth.probability if worth is not None else None, error)

    def observe(self, subject: str, exchange, **options) -> Observation:
        """`aobserve` for code without an event loop."""
        return run(self.aobserve(subject, exchange, **options))

    async def areflect(self, subject: str, *, user: str = "the user", complete=None) -> str | None:
        """Rewrite the subject's profile card from their notes (once a day is plenty)."""
        return await areflect(self, subject, user=user, complete=complete)

    def report(self) -> dict:
        """What each tier has answered, abstained on or failed, and what the paid ones cost."""
        return {"decisions": self.decider.report(), "meaning": self.meaning.report() if self.meaning else None}

    # ---- moving between projects ------------------------------------------------------------------
    def export_data(self) -> dict:
        """This space as plain JSON (see docs/FORMAT.md)."""
        return self.store.export_data(self.space)

    def import_data(self, data: dict) -> int:
        """Add an export to this space; returns how many notes were added."""
        return self.store.import_data(data, self.space)

    def close(self) -> None:
        if self.micro is not None:
            self.micro.flush()
        self.store.close()

    def __enter__(self) -> "Mneme":
        return self

    def __exit__(self, *_) -> None:
        self.close()


__all__ = ["Answer", "Chain", "Choice", "Embeddings", "Emotion", "KINDS", "Luna", "Meaning", "Memory", "Mneme",
           "Mood", "MoodEvent", "MoodSettings", "Note", "Observation", "OpenAIEmbeddings", "Predicate", "Prompt",
           "Recall", "Score", "Store", "Unify", "__version__"]
