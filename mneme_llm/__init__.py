"""mneme-llm: memory and mood for AI companions, kept in one SQLite file that any model, and any project, can use.

    from mneme_llm import Mneme
    m = Mneme("companion.db", space="dafeiyu", config="dafeiyu.toml", complete=my_model)
    m.relate("discord:42", "creator")
    m.alias("discord:42", "鲸酱")
    m.remember("discord:42", "养了一只叫年糕的猫", kind="fact", key="pet.name", importance=4)
    system_prompt += await m.aprompt("discord:42", query=user_message, user_name="Leo")
    await m.aobserve("discord:42", [("Leo", user_message), ("大肥鱼", reply)], user_name="Leo")

Swap the model behind your app and point it at the same file: the facts, the history and the mood carry over.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Callable

from . import dates, exchange as exchanges, providers
from .aliases import Aliases
from .capture import WORTH_NAME, notes_in, reflect_prompt, worth, writer_prompt
from .config import STORED, Config
from .decide import Answer, Chain, Choice, Luna, Predicate, Prompt, Score, fit
from .i18n import Words, say
from .meaning import Embeddings, Meaning, OpenAIEmbeddings, ledger
from .memory import KINDS, Memory, Note, Recall
from .mood import Emotion, Mood, MoodEvent, MoodSettings
from .providers import Unavailable, run
from .relations import Relations, Relationship, Role
from .store import SCHEMA_VERSION, Store

__version__ = "0.2.0"


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

    config         the companion's config file (TOML; or a table already read), taken when the database first
                   meets this space: its name, languages and settings, its roles and feelings, its prompts and
                   sentences (`config.py`). From then on the database keeps its own copy (`m.config`), whatever
                   file is given. Each setting below that is left out comes from that copy; one given here wins
                   for this process and is not stored.
    display_language  the language of everything shown to people and to the chat model: the notes' header,
                   dates, moods, tool replies ("en", "zh", or one the config gives sentences for)
    companion_name the companion's own name (the person's is given per call, as `user_name`)
    complete       your own chat model, `complete(system, user) -> str` (sync or async). It is the last tier of
                   decisions and of meaning, and it writes notes (`observe`, `capture`) and the profile card
                   (`reflect`). It can be a fixed, cheap model whatever model your conversation uses.
    luna, micro    decision tiers 1 and 2: True uses GPT-6 Luna's Decisions API when OPENAI_API_KEY is set (it
                   falls through without one) and keeps the local micro model; False leaves either out; or pass
                   a tier of your own.
    embed          meaning tier 1: True uses OpenAI embeddings when OPENAI_API_KEY is set; or pass any embedder
                   (`Embeddings(fn, name=...)` for your own function); False leaves it out.
    meaning_micro  meaning tier 2: word centroids learned from tier 1 (False leaves it out).
    memory_language  meaning tier 3: the language notes are unified into ("English" by default), or a `Unify`
                   of your own; None turns it off.
    roles          what people can be to the companion (`relate`): creator, family, friend, acquaintance, and any
                   `Role` of your own.
    """
    WRITER_INPUT = 12000  # characters of an exchange the note writer reads: its opening and its newest words

    def __init__(self, path: str = "mneme.db", space: str = "default", *, config=None,
                 display_language: str = STORED, companion_name: str = STORED, zone: tzinfo | None = STORED,
                 complete=None, luna=True, micro=True, embed=True, meaning_micro=True, memory_language=STORED,
                 mood: MoodSettings = STORED, roles: tuple[Role, ...] = STORED, half_life_days: float = STORED,
                 daily_quota: int = STORED, clock: Callable[[], float] = time.time):
        self.store = Store(path)
        try:
            ledger.repair(self.store)  # centroids changed by something that kept no account start over
            self.config = Config(self.store, space, clock)
            self.config.seed(config)  # a new companion: the file over the defaults; otherwise its own copy
        except BaseException:
            self.store.close()
            raise
        own = self.config

        def stored(given, key):
            return own.get(key) if given is STORED else given
        if memory_language is STORED:
            memory_language = own.get("companion.memory_language") or None  # "" turns the tier off
        self.space, self.complete, self.prompts = space, complete, own.prompts()
        self.companion_name = stored(companion_name, "companion.name")
        zone = own.zone() if zone is STORED else zone
        words = Words(stored(display_language, "companion.display_language"), own.messages())
        self._tiers = [Luna() if luna is True else luna] if luna else []
        Micro = _optional("decide.micro", "Micro") if micro is True else None
        self.micro = (Micro(self.store) if Micro is not None else None) if micro is True else micro or None
        self._tiers += [self.micro] if self.micro is not None else []
        self.decider = self._chain(complete)
        self.meaning = self._meaning(embed, meaning_micro, memory_language, complete)
        self.memory = Memory(self.store, space, half_life_days=stored(half_life_days, "memory.half_life_days"),
                             daily_quota=stored(daily_quota, "memory.daily_quota"),
                             max_notes=own.get("memory.max_notes"), semantic_window=own.get("memory.semantic_window"),
                             zone=zone, display_language=words, meaning=self.meaning, clock=clock)
        self.mood = Mood(self.store, space, decider=self.decider, settings=own.mood_settings() if mood is STORED
                         else mood, companion_name=self.companion_name, display_language=words, prompts=self.prompts,
                         clock=clock)
        self.relations = Relations(self.store, space, roles=own.roles() if roles is STORED else roles,
                                   growth=own.get("relations.growth"),
                                   fade_days=own.get("relations.fade_days"), zone=zone, display_language=words,
                                   clock=clock)
        self.aliases = Aliases(self.store, space, display_language=words, clock=clock)

    @property
    def display_language(self) -> str:
        return self.memory.display_language

    @display_language.setter
    def display_language(self, language: str) -> None:
        for part in (self.memory, self.mood, self.relations, self.aliases):
            part.display_language = language

    def _chain(self, complete) -> Chain:
        return Chain(*self._tiers, Prompt(complete, system=self.prompts["judge"]) if complete is not None else None)

    def _meaning(self, embed, meaning_micro, memory_language, complete) -> Meaning | None:
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
        unify = None
        if isinstance(memory_language, str) and memory_language.strip():  # a language: the tier, made here
            Unify = _optional("meaning.unify", "Unify")
            unify = Unify(complete, memory_language, prompts=self.prompts) if Unify is not None else None
        elif memory_language:  # a tier of the host's own
            unify = memory_language
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

    def relate(self, subject: str, role: str, *, closeness: float | None = None) -> Relationship:
        """Say who a person is to the companion (see `Relations.set`): "creator" (one per space), "family",
        "friend", "acquaintance" or a role of your own, with a closeness from 0 to 100 within the role's band.
        Their words then move the mood by their closeness, and the prompt says who they are."""
        return self.relations.set(subject, role, closeness=closeness)

    def alias(self, subject: str, alias: str | None) -> str | None:
        """Record what a person calls the companion (see `Aliases.set`), or take it away with None. The prompt then
        tells the companion: "(Leo calls you 鲸酱.)". Your code sets it, never a model."""
        if alias is None:
            self.aliases.remove(subject)
            return None
        return self.aliases.set(subject, alias)

    def forget(self, subject: str, *, id: int | None = None, key: str | None = None) -> int:
        """Hide a note (by id) or a key's live note; it stays in the history until `purge`."""
        return self.memory.forget(subject, id=id, key=key)

    def purge(self, subject: str | None = None) -> int:
        """Erase hidden and replaced notes for good (all subjects when none is given)."""
        return self.memory.purge(subject)

    def erase(self, subject: str) -> int:
        """Everything about a person, gone for good ("forget me"): notes, history, vectors, what they taught the
        word centroids, profile card, recall log, mood and its timeline, their role and their alias. Returns how
        many notes there were."""
        with self.store.transaction():
            count = self.memory.erase(subject)
            self.mood.reset(subject)
            self.relations.remove(subject)
            self.aliases.remove(subject)
        return count

    def prompt(self, subject: str, query: str = "", *, user_name: str | None = None, mark: bool = True, limit: int = 6,
               budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None) -> str:
        """What to add to the system prompt this turn (word matching only): who the person is to the companion and
        what they call it, notes for `query`, and the mood's news, told once. `user_name` is how they are named; the rest is as in
        `Memory.context`."""
        notes = self.memory.context(subject, query, user_name=user_name, limit=limit, budget=budget,
                                    important=important, recent=recent, header=header)
        return self._prompt(subject, user_name, notes, mark)

    async def aprompt(self, subject: str, query: str = "", *, user_name: str | None = None, mark: bool = True,
                      limit: int = 6, budget: int = 800, important: int = 2, recent: int = 1,
                      header: str | None = None, complete=None) -> str:
        """`prompt` with the meaning tiers."""
        notes = await self.memory.acontext(subject, query, user_name=user_name, limit=limit, budget=budget,
                                           important=important, recent=recent, header=header, complete=complete)
        return self._prompt(subject, user_name, notes, mark)

    def _prompt(self, subject: str, user_name: str | None, notes: str, mark: bool) -> str:
        parts = (self.relations.line(subject, user_name), self.aliases.line(subject, user_name), notes,
                 self.mood.news(subject, mark=mark) or "")
        return "\n\n".join(part for part in parts if part)

    async def aobserve(self, subject: str, exchange, *, source: str = "user", user_name: str = "the user",
                       complete=None, mood: bool = True, capture: bool = True, gate: float = 0.5) -> Observation:
        """Call after each exchange, once the reply is out: judges the mood and keeps what is worth remembering.

        One decision request answers both the mood questions and "worth remembering?", so the note writer is
        only called when there is something to write. Notes are only taken from exchanges the person started
        (`source="user"`), and such an exchange is a day of contact for their closeness. The mood moves by how
        close the person is (`relate`). `complete` gives this call a chat model in place of the one given at
        start. If the note writer fails, the mood is still applied and the failure is in `Observation.error`.
        """
        exchange = exchanges.as_text(exchange)  # once (it may be a generator); a wrong one is the caller's mistake
        writer = complete or self.complete
        decider = self._decider(complete)
        judge_mood = mood and source not in self.mood.settings.skip
        keep_notes = capture and source == "user" and writer is not None
        questions = (self.mood.questions() if judge_mood else []) + ([self._worth()] if keep_notes else [])
        answers = {}
        if questions and decider.tiers:
            framed = exchanges.frame(exchange, source=source, user_name=user_name,
                                     companion_name=self.companion_name, prompts=self.prompts)
            answers = await decider.adecide(framed, questions)
        event = (self.mood.apply_answers(subject, answers, exchange, source=source, user_name=user_name,
                                         weight=self.relations.weight(subject)) if judge_mood else None)
        if source == "user":
            self.relations.seen(subject)
        notes, worth, error = [], answers.get(WORTH_NAME), ""
        if keep_notes:
            try:
                notes = await self._capture(subject, exchange, user_name, worth, gate, writer)
            except Exception as failure:  # the note writer is the host's model: report it, keep the mood
                error = f"{type(failure).__name__}: {failure}"[:300]
        return Observation(event, notes, worth.probability if worth is not None else None, error)

    def observe(self, subject: str, exchange, **options) -> Observation:
        """`aobserve` for code without an event loop."""
        return run(self.aobserve(subject, exchange, **options))

    async def acapture(self, subject: str, exchange, *, user_name: str = "the user", gate: float = 0.5,
                       complete=None) -> list[Note]:
        """Notes kept from one exchange, without judging the mood (source "auto", so the daily quota applies).
        "Worth remembering?" is asked first when a decision tier is there; the note writer only when it says yes."""
        found = None
        decider = self._decider(complete)
        if decider.tiers and gate > 0:
            framed = exchanges.frame(exchange, source="user", user_name=user_name, companion_name=self.companion_name,
                                     prompts=self.prompts)
            found = (await decider.adecide(framed, [self._worth()])).get(WORTH_NAME)
        return await self._capture(subject, exchange, user_name, found, gate, complete or self.complete)

    def _worth(self):
        return worth(self.prompts["worth"])

    def capture(self, subject: str, exchange, **options) -> list[Note]:
        """`acapture` for code without an event loop."""
        return run(self.acapture(subject, exchange, **options))

    async def _capture(self, subject: str, exchange, user_name: str, worth: Answer | None, gate: float,
                       complete) -> list[Note]:
        if worth is not None and worth.probability < gate:
            return []
        exchange = fit(exchanges.as_text(exchange), self.WRITER_INPUT)  # a huge exchange: its opening and its end
        memory = self.memory
        known = [item.note.text for item in memory.recall(subject, exchange, log=False).chosen]
        unify = self.meaning.unify if self.meaning is not None else None
        today = dates.local(memory.clock(), memory.zone).strftime("%Y-%m-%d (%A)")
        system = writer_prompt(user_name, known, today, getattr(unify, "language", None) if unify else None,
                               prompts=self.prompts)
        reply = await providers.ask(complete, system, exchange)
        kept = []
        for fields in notes_in(reply, memory.clock(), memory.zone):
            note = memory.remember(subject, source="auto", **fields)
            if note is not None:
                kept.append(note)
        if kept and self.meaning is not None:
            await self.meaning.prepare_vectors(kept)  # embed now, after the reply, rather than at the next recall
        return kept

    async def areflect(self, subject: str, *, user_name: str = "the user", limit: int = 60,
                       complete=None) -> str | None:
        """Rewrite the person's profile card from their most important and newest notes (once a day is plenty);
        returns the new card."""
        notes = self.memory.leading(subject, limit)
        if not notes:
            return None
        system = reflect_prompt(user_name, self.companion_name, say(self.memory.words, "reflect.language"), notes,
                                prompts=self.prompts)
        card = (await providers.ask(complete or self.complete, system, "Write the impression now.")).strip()
        if card:
            self.memory.set_profile(subject, card)
        return card or None

    def reflect(self, subject: str, **options) -> str | None:
        """`areflect` for code without an event loop."""
        return run(self.areflect(subject, **options))

    async def aregloss(self, subject: str | None = None, *, everything: bool = False, complete=None) -> int:
        """Gloss again, in full, the notes that need it (one subject, or all): those with no gloss, and those
        whose gloss is still their own text in another script (the model could not gloss them before); with
        `everything`, every note in another script. Unlike a recall, this asks as many times as it takes and
        forgets what failed before. Returns how many glosses were written."""
        unify = self.meaning.unify if self.meaning is not None else None
        if unify is None:
            return 0
        written = 0
        for who in [subject] if subject is not None else self.memory.subjects():
            notes = [note for note in self.memory.notes(who) if unify.needs_translation(note.text) and
                     (everything or not note.gloss or note.gloss == note.text)]
            unify.forget_failures([note.id for note in notes])
            pending = [dataclasses.replace(note, gloss=None) for note in notes]
            found = await unify.glosses(pending, complete=complete, calls=len(pending) * 2 + 1)
            self.memory.write_glosses(found, replace=True)
            written += len(found)
        return written

    def regloss(self, subject: str | None = None, **options) -> int:
        """`aregloss` for code without an event loop."""
        return run(self.aregloss(subject, **options))

    def report(self) -> dict:
        """What each tier has answered, abstained on or failed, and what the paid ones cost."""
        return {"decisions": self.decider.report(), "meaning": self.meaning.report() if self.meaning else None}

    # ---- moving between projects ------------------------------------------------------------------
    def export_data(self) -> dict:
        """This space as plain JSON (see docs/FORMAT.md), its config included."""
        return {"mneme_llm": SCHEMA_VERSION, "space": self.space, "exported_at": time.time(),
                **self.memory.export_rows(), **self.mood.export_rows(), **self.relations.export_rows(),
                **self.aliases.export_rows(), **self.config.export_rows()}

    def import_data(self, data: dict, *, config: bool = False) -> int:
        """Add an export to this space, held to the rules of writing; returns how many notes were added. The
        export's config (its prompts are instructions to your models) is applied only with `config=True`, and
        is in use once the file is next opened."""
        if not isinstance(data, dict):
            raise TypeError("an export is a JSON object")
        rows = {name: data.get(name) if isinstance(data.get(name), list) else []
                for name in ("memories", "profiles", "moods", "mood_events", "relationships", "aliases", "config")}
        with self.store.transaction():
            added = self.memory.import_rows(rows["memories"], rows["profiles"])
            self.mood.import_rows(rows["moods"], rows["mood_events"])
            self.relations.import_rows(rows["relationships"])
            self.aliases.import_rows(rows["aliases"])
            if config:
                self.config.import_rows(rows["config"])
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


__all__ = ["Aliases", "Answer", "Chain", "Choice", "Config", "Embeddings", "Emotion", "KINDS", "Luna", "Meaning", "Memory",
           "Mneme", "Mood", "MoodEvent", "MoodSettings", "Note", "Observation", "OpenAIEmbeddings", "Predicate",
           "Prompt", "Recall", "Relations", "Relationship", "Role", "STORED", "Score", "Store", "Unavailable",
           "__version__"]
