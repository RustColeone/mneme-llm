"""mneme-llm: memory and mood for AI companions, kept in one SQLite file that any model, and any project, can use.

    from mneme_llm import Mneme
    m = Mneme("companion.db", space="whale_chan", lang="zh")
    m.remember("discord:42", "养了一只叫年糕的猫", kind="fact", key="pet.name", importance=4)
    system_prompt += m.prompt("discord:42", query=user_message)

Swap the model behind your app and point it at the same file: the facts, the history and the mood carry over.
"""

from __future__ import annotations

import time
from datetime import tzinfo
from typing import Callable

from .decide import Answer, Chain, Choice, Luna, Predicate, Prompt, Score
from .memory import KINDS, Memory, Note, Recall
from .mood import Emotion, Mood, MoodSettings
from .store import Store

__version__ = "0.1.0"


class Mneme:
    """Memory, mood and the decision chain of one space, in one object.

    luna      True: use the Decisions API when OPENAI_API_KEY is set (falls through without it); False: never;
              or pass your own `Luna(...)`.
    micro     True: keep the local micro model (learns from Luna, answers once it is trusted); False: leave it out.
    complete  Your own chat model, `complete(system, user) -> str` (sync or async): the last tier, and what
              writes notes and the profile card in `capture`/`reflect`.
    """

    def __init__(self, path: str = "mneme.db", space: str = "default", *, lang: str = "en", name: str = "the assistant",
                 zone: tzinfo | None = None, luna=True, micro=True, complete=None,
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
        self.memory = Memory(self.store, space, half_life_days=half_life_days, daily_quota=daily_quota, zone=zone,
                             lang=lang, clock=clock)
        self.mood = Mood(self.store, space, decider=self.decider, settings=mood, name=name, lang=lang, clock=clock)

    # ---- the few calls most programs need ------------------------------------------------------------
    def remember(self, subject: str, text: str, **options) -> Note | None:
        return self.memory.remember(subject, text, **options)

    def recall(self, subject: str, query: str, **options) -> Recall:
        return self.memory.recall(subject, query, **options)

    def forget(self, subject: str, **options) -> int:
        return self.memory.forget(subject, **options)

    def prompt(self, subject: str, query: str = "", *, name: str | None = None, mark: bool = True,
               **options) -> str:
        """What to add to the system prompt this turn: memories for `query`, and her mood's news (once)."""
        parts = [self.memory.context(subject, query, name=name, **options), self.mood.news(subject, mark=mark) or ""]
        return "\n\n".join(part for part in parts if part)

    async def aafter(self, subject: str, exchange, *, source: str = "user", user: str = "the user", complete=None):
        """Call after each exchange: judges the mood (and teaches the micro model). Returns the mood change.

        `complete` gives the last tier a chat model for this call only, in place of the one given at start."""
        decider = None
        if complete is not None:
            decider = Chain(*[tier for tier in self.decider.tiers if tier.name != "prompt"], Prompt(complete))
            decider.stats = self.decider.stats  # one report for both
        return await self.mood.ajudge(subject, exchange, source=source, user=user, decider=decider)

    def after(self, subject: str, exchange, **options):
        from .decide import run
        return run(self.aafter(subject, exchange, **options))

    # ---- moving between projects ------------------------------------------------------------------
    def export(self) -> dict:
        return self.store.export(self.space)

    def import_(self, data: dict) -> int:
        return self.store.import_(data, self.space)

    def close(self) -> None:
        if self.micro is not None:
            self.micro.flush()
        self.store.close()

    def __enter__(self) -> "Mneme":
        return self

    def __exit__(self, *_) -> None:
        self.close()


__all__ = ["Answer", "Chain", "Choice", "Emotion", "KINDS", "Luna", "Memory", "Mneme", "Mood", "MoodSettings",
           "Note", "Predicate", "Prompt", "Recall", "Score", "Store", "__version__"]
