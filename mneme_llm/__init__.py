"""mneme-llm: memory and mood for AI companions, kept in one SQLite file that any model, and any project, can use.

    from mneme_llm import Mneme
    m = Mneme("companion.db", space="dafeiyu", config="dafeiyu.toml", complete=my_model)
    m.relate("discord:42", "creator")
    m.alias("discord:42", "鲸酱")
    m.link("web:leo", "discord:42")   # the same person on another account
    m.remember("discord:42", "养了一只叫年糕的猫", kind="fact", key="pet.name", importance=4)
    system_prompt += await m.aprompt("discord:42", query=user_message, user_name="Leo", said=6000)
    await m.aobserve("discord:42", [("Leo", user_message), ("大肥鱼", reply)], user_name="Leo")
    context = m.surface.read("discord:42").messages   # what was said lately, as real turns (`surface.py`)

Swap the model behind your app and point it at the same file: the facts, the history and the mood carry over.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Callable

from . import dates, exchange as exchanges, providers, text as texts
from .aliases import Aliases
from .capture import WORTH_NAME, notes_in, reflect_prompt, worth, writer_prompt
from .config import STORED, Config
from .decide import Answer, Choice, Predicate, Prompt, Score
from .episodes import Episode, Episodes
from .gut import Gut, Turn
from .i18n import Words, say
from .meaning import Embeddings, Meaning, OpenAIEmbeddings
from .memory import KINDS, Memory, Note, Recall
from .mood import LEVELS, Emotion, Mood, MoodEvent, MoodSettings
from .people import People
from .providers import Unavailable, run
from .relations import Relations, Relationship, Role
from .store import SCHEMA_VERSION, Store
from .surface import Card, First, Surface, View

__version__ = "0.6.0"
SEARCHED = 5  # exchanges a search adds to a look
log = logging.getLogger("mneme_llm")


def _optional(module: str, name: str):
    """A removable tier's class, or None when its file was deleted from this install."""
    try:
        return getattr(__import__(f"mneme_llm.{module}", fromlist=[name]), name)
    except ImportError:
        return None


@dataclass(frozen=True)
class Observation:
    """What `observe` made of one exchange: the mood change (None when nothing moved), the notes kept and the
    exchange itself, kept word for word."""
    mood: MoodEvent | None = None
    notes: list = field(default_factory=list)
    worth: float | None = None  # how likely the exchange held something worth remembering, when it was asked
    error: str = ""             # why notes could not be written (the note writer failed), if they could not
    episode: Episode | None = None


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
    complete       your own chat model, `complete(system, user) -> str` (sync or async). It answers the small
                   decisions, is the last tier of meaning, and writes notes (`observe`, `capture`) and the profile
                   card (`reflect`). It can be a fixed, cheap model whatever model your conversation uses.
    judge          a judge of your own, answering the small decisions in place of `complete` (`decide.py`)
    embed          meaning tier 1: True uses OpenAI embeddings when OPENAI_API_KEY is set; or pass any embedder
                   (`Embeddings(fn, name=...)` for your own function); False leaves it out.
    memory_language  meaning tier 2: the language notes are unified into ("English" by default), or a `Unify`
                   of your own; None turns it off.
    roles          what people can be to the companion (`relate`): creator, family, friend, acquaintance, and any
                   `Role` of your own.
    surface_days, surface_floor, surface_cap, surface_window
                   how much of the conversation stays as real turns (`surface.py`): set them as high as you like
    """
    WRITER_INPUT = 12000  # characters of an exchange the note writer reads: its opening and its newest words

    def __init__(self, path: str = "mneme.db", space: str = "default", *, config=None,
                 display_language: str = STORED, companion_name: str = STORED, zone: tzinfo | None = STORED,
                 complete=None, judge=None, embed=True, memory_language=STORED,
                 mood: MoodSettings = STORED, roles: tuple[Role, ...] = STORED, half_life_days: float = STORED,
                 daily_quota: int = STORED, surface_days: int = STORED, surface_floor: int = STORED,
                 surface_cap: int = STORED, surface_window: int = STORED, clock: Callable[[], float] = time.time):
        self.store = Store(path)
        try:
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
        self.judge = judge
        self.decisions = {"answered": 0, "abstained": 0, "failed": 0, "last_error": ""}
        self.meaning = self._meaning(embed, memory_language, complete)
        self.people = People(self.store, space)
        self.memory = Memory(self.store, space, half_life_days=stored(half_life_days, "memory.half_life_days"),
                             daily_quota=stored(daily_quota, "memory.daily_quota"),
                             max_notes=own.get("memory.max_notes"), semantic_window=own.get("memory.semantic_window"),
                             zone=zone, display_language=words, meaning=self.meaning, people=self.people,
                             clock=clock)
        self.mood = Mood(self.store, space, settings=own.mood_settings() if mood is STORED else mood,
                         companion_name=self.companion_name, display_language=words, prompts=self.prompts,
                         people=self.people, clock=clock)
        self.relations = Relations(self.store, space, roles=own.roles() if roles is STORED else roles,
                                   liking=own.get("relations.liking"),
                                   fade_days=own.get("relations.fade_days"), zone=zone, display_language=words,
                                   people=self.people, clock=clock, config=own)
        self.aliases = Aliases(self.store, space, display_language=words, people=self.people, clock=clock)
        self.episodes = Episodes(self.store, space, days=own.get("memory.said_days"), zone=zone,
                                 display_language=words, meaning=self.meaning, people=self.people, clock=clock)
        self.surface = Surface(self.store, space, self.episodes, days=stored(surface_days, "memory.surface_days"),
                               floor=stored(surface_floor, "memory.surface_floor"),
                               cap=stored(surface_cap, "memory.surface_cap"),
                               window=stored(surface_window, "memory.surface_window"),
                               companion_name=self.companion_name,
                               display_language=words, prompts=self.prompts, people=self.people, complete=complete,
                               clock=clock)
        self.said_budget = own.get("memory.said_budget")
        fresh = own.get("memory.said_cut")  # (a faded exchange's bar is never under a fresh one's; −1: none)
        self.said_cut = (fresh, max(fresh, own.get("memory.said_cut_faded")))
        self.said_words = own.get("memory.said_words")  # (with words alone)

    @property
    def display_language(self) -> str:
        return self.memory.display_language

    @display_language.setter
    def display_language(self, language: str) -> None:
        for part in (self.memory, self.mood, self.relations, self.aliases, self.episodes, self.surface):
            part.display_language = language

    def _meaning(self, embed, memory_language, complete) -> Meaning | None:
        embedder = None
        if embed is True:
            embedder = OpenAIEmbeddings()
        elif callable(embed) and not hasattr(embed, "embed"):
            embedder = Embeddings(embed, name=f"custom:{getattr(embed, '__qualname__', 'function')}")
        elif embed:
            embedder = embed
        unify = None
        if isinstance(memory_language, str) and memory_language.strip():  # a language: the tier, made here
            Unify = _optional("meaning.unify", "Unify")
            unify = Unify(complete, memory_language, prompts=self.prompts) if Unify is not None else None
        elif memory_language:  # a tier of the host's own
            unify = memory_language
        if embedder is None and unify is None:
            return None
        return Meaning(self.store, embedder, unify)

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

    def link(self, subject: str, person: str) -> str:
        """Record that `subject` is the same person as `person` (another account of theirs; see `People`): from now
        on every call with either means them, and what was kept under `subject` joins what is kept under `person`.
        Your code links accounts it knows to be one person, never a model. Returns the person's own subject."""
        with self.store.transaction():
            person, new = self.people.link(subject, person)
            if new:
                self._join(subject, person)
        return person

    def unlink(self, subject: str) -> bool:
        """`subject` is its own person again from now on; what was joined stays with the person it was linked to."""
        return self.people.unlink(subject)

    def person(self, subject: str) -> str:
        """The person a subject stands for: the subject it is linked to, or itself."""
        return self.people.of(subject)

    def _join(self, old: str, new: str) -> None:
        for part in (self.memory, self.mood, self.relations, self.aliases, self.surface, self.episodes):
            part.join(old, new)

    def forget(self, subject: str, *, id: int | None = None, key: str | None = None) -> int:
        """Hide a note (by id) or a key's live note; it stays in the history until `purge`."""
        return self.memory.forget(subject, id=id, key=key)

    def purge(self, subject: str | None = None) -> int:
        """Erase hidden and replaced notes for good (all subjects when none is given)."""
        return self.memory.purge(subject)

    def erase(self, subject: str) -> int:
        """Everything about a person, gone for good ("forget me"): notes, history, vectors, profile card, recall log,
        every exchange kept word for word, the surface and their Character Card, mood and its timeline, their role, their
        alias and the links of their other accounts. Returns how many notes there were."""
        with self.store.transaction():
            subject = self.people.of(subject)
            count = self.memory.erase(subject)
            self.episodes.erase(subject)
            self.surface.erase(subject)
            self.mood.reset(subject)
            self.relations.remove(subject)
            self.aliases.remove(subject)
            self.people.remove(subject)
        return count

    def everyone(self) -> list[str]:
        """Everyone anything is kept of, in order."""
        return sorted({*self.memory.subjects(), *self.episodes.subjects(), *self.surface.subjects()})

    def wipe(self, subject: str) -> int:
        """What she remembers of a person gone for good: notes, profile card, every exchange, the surface and their
        Character Card. Who they are to her stays: their role, closeness, alias, mood and accounts, and whatever a gut
        kept apart learned from them. Returns how many exchanges there were."""
        with self.store.transaction():
            subject = self.people.of(subject)
            self.memory.erase(subject)
            count = self.episodes.erase(subject)
            self.surface.erase(subject)
        return count

    def prompt(self, subject: str, query: str = "", *, user_name: str | None = None, mark: bool = True, limit: int = 6,
               budget: int = 800, important: int = 2, recent: int = 1, header: str | None = None, said: int = 0,
               search: bool = False, own: bool = False) -> str:
        """What to add to the system prompt this turn (word matching only): who the person is to the companion and
        what they call it, notes for `query`, with `said` (a budget of characters) what was said before that
        bears on it (`look`), and the mood's news, told once. `user_name` is how they are named; the notes' options
        are as in `Memory.context`, the rest as in `look`."""
        notes = self.memory.context(subject, query, user_name=user_name, limit=limit, budget=budget,
                                    important=important, recent=recent, header=header)
        words = self.look(subject, query, user_name=user_name, budget=said, search=search, own=own) if said else ""
        return self._prompt(subject, user_name, notes, words, mark)

    async def aprompt(self, subject: str, query: str = "", *, user_name: str | None = None, mark: bool = True,
                      limit: int = 6, budget: int = 800, important: int = 2, recent: int = 1,
                      header: str | None = None, complete=None, said: int = 0, search: bool = False,
                      own: bool = False) -> str:
        """`prompt` with the meaning tiers."""
        notes = await self.memory.acontext(subject, query, user_name=user_name, limit=limit, budget=budget,
                                           important=important, recent=recent, header=header, complete=complete)
        words = await self.alook(subject, query, user_name=user_name, budget=said, search=search,
                                 own=own) if said else ""
        return self._prompt(subject, user_name, notes, words, mark)

    def _prompt(self, subject: str, user_name: str | None, notes: str, said: str, mark: bool) -> str:
        parts = (self.relations.line(subject, user_name), self.aliases.line(subject, user_name), notes, said,
                 self.mood.news(subject, mark=mark) or "")
        return "\n\n".join(part for part in parts if part)

    def look(self, subject: str, query: str = "", *, user_name: str | None = None, budget: int | None = None,
             search: bool = False, own: bool = False, found: int = SEARCHED, skip=None) -> str:
        """What was said before that bears on `query` (word matching only), ready for a prompt: the best matches word
        for word within `budget` characters (`memory.said_budget`, 6,000, when not given), under a header that asks for
        the person check. With meaning (`alook`), only what is close enough comes, and the more an exchange has faded,
        the closer it must be (`memory.said_cut`, `memory.said_cut_faded`): often nothing. With words alone,
        `memory.said_words` is the bar: the share of the query's weight an exchange must share (0.25 as it ships; 0:
        none).

        `search`: your model has the search tool (`tools.py`). Then a search comes with the look, `found` exchanges by
        relevance alone however faded, and the model is told to search before it says it does not remember. So a
        question about something old finds it, with nothing to decide whether it was one, and what the conversation
        still shows is found too, as a block that left it out reads as if she has forgotten it. In a group give
        `found=0`: a search has no bar, and what was said in private must not come up by itself where others read.

        `own`: this is the person's own conversation with the companion, what they said to it in the first place, so no
        data label. Their same question asked before is left out: all it holds is what she said then, and an "I don't
        remember" found again is said again.

        `skip`: ids of exchanges to leave out, such as those the conversation in front of the model still shows. ""
        when nothing bears on it and there is no search."""
        came = self.episodes.look(subject, query, budget=self._said(budget), cut=self.said_cut,
                                  more=found if search else 0, skip=skip, words_cut=self.said_words)
        return self._came_back(came, query, user_name, search, own)

    async def alook(self, subject: str, query: str = "", *, user_name: str | None = None, budget: int | None = None,
                    search: bool = False, own: bool = False, found: int = SEARCHED, skip=None) -> str:
        """`look` with meaning (the query's embedding, when it comes within a few seconds)."""
        came = await self.episodes.alook(subject, query, budget=self._said(budget), cut=self.said_cut,
                                         more=found if search else 0, skip=skip, words_cut=self.said_words)
        return self._came_back(came, query, user_name, search, own)

    def _came_back(self, came: list[Episode], query: str, user_name: str | None, search: bool, own: bool) -> str:
        same = "".join(query.split())
        came = [item for item in came if "".join(item.lines[0][1].split()) != same]
        return self.episodes.render(came, user_name=user_name, search=search, own=own)

    def _said(self, budget: int | None) -> int:
        return self.said_budget if budget is None else max(0, int(budget))

    async def aobserve(self, subject: str, exchange, *, source: str = "user", user_name: str = "the user",
                       complete=None, mood: bool = True, capture: bool = True, gate: float = 0.5, keep: bool = True,
                       conversation: str = "", at: float | None = None) -> Observation:
        """Call after each exchange, once the reply is out: keeps it word for word, judges the mood and keeps what
        is worth remembering.

        An exchange the person started (`source="user"`) is kept word for word first (`keep`; no model call), with
        when (`at`, now when not given) and where (`conversation`) it was said, and then embedded. One decision
        request answers both the mood questions and "worth remembering?", so the note writer is only called when
        there is something to write. Notes, too, are only taken from exchanges the person started, and such an
        exchange moves their closeness by how it moved her mood. The mood moves by how close the person is (`relate`).
        `complete` gives this call a chat model in place of the one given at start. If the note writer fails, the
        mood is still applied and the failure is in `Observation.error`.
        """
        lines = exchanges.as_lines(exchange)  # once (it may be a generator); a wrong one is the caller's mistake
        exchange = exchanges.text_of(lines)
        episode = self.episodes.keep(subject, lines, at=at, conversation=conversation) \
            if keep and source == "user" else None
        writer = complete or self.complete
        judge_mood = mood and source not in self.mood.settings.skip
        keep_notes = capture and source == "user" and writer is not None
        questions = (self.mood.questions() if judge_mood else []) + ([self._worth()] if keep_notes else [])
        answers = await self._decide(exchange, questions, source, user_name, complete)
        event = (self.mood.apply_answers(subject, answers, exchange, source=source, user_name=user_name,
                                         weight=self.relations.weight(subject)) if judge_mood else None)
        if source == "user":
            change = answers.get("mood_change") if judge_mood else None
            self.relations.seen(subject, change.mean(LEVELS) if change else None)
            if keep:
                self.surface.noticed(subject, lines)
        notes, worth, error = [], answers.get(WORTH_NAME), ""
        if keep_notes:
            try:
                notes = await self._capture(subject, exchange, user_name, worth, gate, writer)
            except Exception as failure:  # the note writer is the host's model: report it, keep the mood
                error = f"{type(failure).__name__}: {failure}"[:300]
        if episode is not None:
            await self.episodes.prepare(episode.subject, first=[episode.id])  # it rehearses what it is about
        return Observation(event, notes, worth.probability if worth is not None else None, error, episode)

    def observe(self, subject: str, exchange, **options) -> Observation:
        """`aobserve` for code without an event loop."""
        return run(self.aobserve(subject, exchange, **options))

    async def acapture(self, subject: str, exchange, *, user_name: str = "the user", gate: float = 0.5,
                       complete=None) -> list[Note]:
        """Notes kept from one exchange, without judging the mood (source "auto", so the daily quota applies).
        "Worth remembering?" is asked first when there is a judge; the note writer only when it says yes."""
        answers = await self._decide(exchange, [self._worth()] if gate > 0 else [], "user", user_name, complete)
        return await self._capture(subject, exchange, user_name, answers.get(WORTH_NAME), gate,
                                   complete or self.complete)

    def _worth(self):
        return worth(self.prompts["worth"])

    async def _decide(self, exchange, questions: list, source: str, user_name: str, complete) -> dict[str, Answer]:
        """What the host's judge, or else the chat model (this call's own when it gives one), answers about an exchange.
        One that fails is logged and answers nothing."""
        complete = complete or self.complete
        if not questions or (self.judge is None and complete is None):
            return {}
        decider = self.judge or Prompt(complete, system=self.prompts["judge"])
        framed = exchanges.frame(exchange, source=source, user_name=user_name, companion_name=self.companion_name,
                                 prompts=self.prompts)
        try:
            answers = await decider.adecide(framed, questions)
        except Exception as error:
            self.decisions["failed"] += 1
            self.decisions["last_error"] = f"{type(error).__name__}: {error}"[:300]
            log.info("the judge failed: %s", self.decisions["last_error"])
            return {}
        found = {question.name: answers[question.name] for question in questions if answers.get(question.name)}
        self.decisions["answered"] += len(found)
        self.decisions["abstained"] += len(questions) - len(found)
        return found

    def capture(self, subject: str, exchange, **options) -> list[Note]:
        """`acapture` for code without an event loop."""
        return run(self.acapture(subject, exchange, **options))

    async def _capture(self, subject: str, exchange, user_name: str, worth: Answer | None, gate: float,
                       complete) -> list[Note]:
        if worth is not None and worth.probability < gate:
            return []
        exchange = texts.fit(exchanges.as_text(exchange), self.WRITER_INPUT)  # a huge exchange: its opening and its end
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
        card = (await providers.ask(complete or self.complete, system, self.prompts["reflect_now"])).strip()
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
        """What the judge has answered, abstained on or failed, and what the meaning tiers did and cost."""
        return {"decisions": dict(self.decisions), "meaning": self.meaning.report() if self.meaning else None}

    # ---- moving between projects ------------------------------------------------------------------
    def export_data(self) -> dict:
        """This space as plain JSON (see docs/FORMAT.md), its config included."""
        return {"mneme_llm": SCHEMA_VERSION, "space": self.space, "exported_at": time.time(),
                **self.memory.export_rows(), **self.mood.export_rows(), **self.relations.export_rows(),
                **self.aliases.export_rows(), **self.people.export_rows(), **self.episodes.export_rows(),
                **self.surface.export_rows(), **self.config.export_rows()}

    def import_data(self, data: dict, *, config: bool = False) -> int:
        """Add an export to this space, held to the rules of writing; returns how many notes were added. Its links
        come along (an account this file links to someone else stays so), and what it kept under a linked account
        joins the person. The export's config (its prompts are instructions to your models) is applied only with
        `config=True`, and is in use once the file is next opened."""
        if not isinstance(data, dict):
            raise TypeError("an export is a JSON object")
        rows = {name: data.get(name) if isinstance(data.get(name), list) else []
                for name in ("memories", "profiles", "moods", "mood_events", "relationships", "aliases", "people",
                             "episodes", "surfaces", "first_prompts", "config")}
        with self.store.transaction():
            added = self.memory.import_rows(rows["memories"], rows["profiles"])
            self.mood.import_rows(rows["moods"], rows["mood_events"])
            self.relations.import_rows(rows["relationships"])
            self.aliases.import_rows(rows["aliases"])
            self.episodes.import_rows(rows["episodes"])
            self.surface.import_rows(rows["surfaces"], rows["first_prompts"])
            for subject, person in self.people.rows_of(rows["people"]):
                try:
                    self.link(subject, person)
                except ValueError:  # linked to someone else here: this file's link stays
                    pass
            for subject, person in self.people.all().items():
                self._join(subject, person)  # what the export kept under a linked account is the person's
            if config:
                self.config.import_rows(rows["config"])
        return added

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "Mneme":
        return self

    def __exit__(self, *_) -> None:
        self.close()


__all__ = ["Aliases", "Answer", "Card", "Choice", "Config", "Embeddings", "Emotion", "Episode", "Episodes", "First", "Gut",
           "KINDS", "Meaning", "Memory", "Mneme", "Mood", "MoodEvent", "MoodSettings", "Note", "Observation",
           "OpenAIEmbeddings", "People", "Predicate", "Prompt", "Recall", "Relations", "Relationship", "Role", "STORED",
           "Score", "Store", "Surface", "Turn", "Unavailable", "View", "__version__"]
