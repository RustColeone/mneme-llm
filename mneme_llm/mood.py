"""A companion's mood toward each person: one value (0-100) and a few feelings, judged after every exchange.

    value       drifts back to `baseline` (70) with a half-life of 3 hours
    emotions    each fades toward 0 with a half-life of 90 minutes
    judgement   after an exchange the decision chain answers two questions (how her mood moved on a -2..+2
                scale, and which feeling was strongest); expected values move the state, so an unsure judge
                moves it little
    guardrails  her mood only drops from aching for them, worry or sadness, never from being cross with them;
                exchanges that change nothing leave no record; a judgement below `threshold` confidence is
                recorded but never told to her ("rather say nothing than put a guess in her mouth")
    telling     `news()` gives the newest change once, for the system prompt; `describe()` any time

Where an exchange came from matters: a person talking to her (`user`), her reaching out on her own
(`speak-up`), or her doing a scheduled task (`duty`) are judged differently; `runtime` turns are skipped.
Decay is computed when read, so nothing has to tick in the background.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from . import dates, exchange as exchanges, text as texts
from .decide import Answer, Chain, Choice, Score
from .i18n import LANGUAGES, has, say
from .providers import run
from .store import Store, dumps


@dataclass(frozen=True)
class Emotion:
    """A feeling the companion can have. The built-in ones are named in `i18n`; a host's own feeling brings its
    names, by language (`{"en": "proud", "zh": "骄傲"}`)."""
    key: str
    lowers: bool = False  # may this feeling pull her mood down?
    names: Mapping[str, str] = field(default_factory=dict)

    def label(self, lang: str) -> str:
        if lang in self.names:
            return self.names[lang]
        return say(lang, f"emotion.{self.key}") if has(f"emotion.{self.key}") else self.names.get("en", self.key)

    def description(self) -> str:
        """For the judge: the name in English, then in the other languages ("happy (开心)")."""
        labels = list(dict.fromkeys(self.label(lang) for lang in LANGUAGES))
        return f"{labels[0]} ({', '.join(labels[1:])})" if len(labels) > 1 else labels[0]


EMOTIONS = (Emotion("happy"), Emotion("calm"), Emotion("sweet"), Emotion("tender", lowers=True),
            Emotion("worried", lowers=True), Emotion("sad", lowers=True), Emotion("jealous"))
FACES = ((80, "great"), (62, "good"), (42, "ok"), (25, "worry"), (0, "sad"))  # named in i18n as face.<name>
LEVELS = {"-2": -2.0, "-1": -1.0, "0": 0.0, "1": 1.0, "2": 2.0}


@dataclass(frozen=True)
class MoodSettings:
    baseline: float = 70.0
    floor: float = 0.0
    ceiling: float = 100.0
    mood_half_life_h: float = 3.0
    emotion_half_life_min: float = 90.0
    step: float = 6.0            # mood points per scale level (+2 → +12 at most per exchange)
    gain: float = 40.0           # emotion points for a certain feeling
    threshold: float = 0.6       # below this the change is kept but not told
    tell: str = "event"          # "event" (what just moved her), "mood" (only how she feels) or "off"
    emotions: tuple[Emotion, ...] = EMOTIONS
    weights: Mapping[str, float] = field(default_factory=lambda: {"user": 1.0, "speak-up": 0.7, "duty": 0.5})
    skip: frozenset = frozenset({"runtime", "time"})


@dataclass(frozen=True)
class MoodState:
    value: float
    emotions: dict[str, float]
    face: str  # great, good, ok, worry or sad (say(lang, f"face.{face}") names it)
    updated_at: float | None

    def strongest(self, count: int = 2, above: float = 5.0) -> list[tuple[str, float]]:
        ranked = sorted(self.emotions.items(), key=lambda item: -item[1])
        return [(key, value) for key, value in ranked[:count] if value >= above]


@dataclass(frozen=True)
class MoodEvent:
    id: int
    at: float
    delta: float
    emotions: dict[str, float]
    reason: str
    confidence: float
    source: str
    judge: str
    value: float


class Mood:
    def __init__(self, store: Store, space: str, *, decider: Chain | None = None,
                 settings: MoodSettings = MoodSettings(), name: str = "the assistant", lang: str = "en",
                 clock: Callable[[], float] = time.time):
        self.store, self.space, self.decider, self.settings = store, space, decider, settings
        self.name, self.lang, self.clock = name, lang, clock

    # ---- reading -------------------------------------------------------------------------------------
    def state(self, subject: str, now: float | None = None) -> MoodState:
        now = self.clock() if now is None else now
        row = self.store.row("select * from moods where space = ? and subject = ?", (self.space, subject))
        s = self.settings
        if row is None:
            return self._state(s.baseline, {}, None)
        hours = max(0.0, now - row["updated_at"]) / 3600
        value = s.baseline + (row["value"] - s.baseline) * 0.5 ** (hours / s.mood_half_life_h)
        fade = 0.5 ** (hours * 60 / s.emotion_half_life_min)
        emotions = {key: amount * fade for key, amount in json.loads(row["emotions"]).items()}
        return self._state(value, emotions, row["updated_at"])

    def describe(self, subject: str) -> str:
        """How the companion feels now, in one line ("Mood 74/100 (good); feeling: aching for them 31")."""
        state = self.state(subject)
        names = {e.key: e.label(self.lang) for e in self.settings.emotions}
        feelings = say(self.lang, "mood.separator").join(f"{names.get(key, key)} {round(value)}"
                                                         for key, value in state.strongest())
        line = say(self.lang, "mood.line", value=round(state.value), face=say(self.lang, f"face.{state.face}"))
        return line + (say(self.lang, "mood.feelings", feelings=feelings) if feelings else "")

    def news(self, subject: str, *, mark: bool = True) -> str | None:
        """The newest confident change, once (None if there is nothing new to tell or telling is off)."""
        s = self.settings
        if s.tell == "off":
            return None
        with self.store.transaction():  # read and marked together, so two prompts at once don't both tell it
            row = self.store.row("select * from moods where space = ? and subject = ?", (self.space, subject))
            if row is None or row["last_event"] is None or row["last_event"] == row["told_event"]:
                return None
            event = self.store.row("select * from mood_events where id = ?", (row["last_event"],))
            if event is None or event["confidence"] < s.threshold:
                return None
            if mark:
                self.store.execute("update moods set told_event = ? where space = ? and subject = ?",
                                   (row["last_event"], self.space, subject))
        mood = self.describe(subject)
        mood = mood if self.lang == "zh" else mood[0].lower() + mood[1:]
        if s.tell == "mood" or not event["reason"]:
            return say(self.lang, "mood.now", mood=mood)
        return say(self.lang, "mood.news", mood=mood, reason=event["reason"])

    def timeline(self, subject: str, limit: int = 40) -> list[MoodEvent]:
        rows = self.store.rows("select * from mood_events where space = ? and subject = ? order by id desc limit ?",
                               (self.space, subject, limit))
        return [MoodEvent(row["id"], row["at"], row["delta"], json.loads(row["emotions"]), row["reason"],
                          row["confidence"], row["source"], row["judge"], row["value"]) for row in rows]

    # ---- changing ------------------------------------------------------------------------------------
    def questions(self) -> list:
        """What the judge is asked. The wording names nobody (who is who, and who started it, is said in the
        judged text: `exchange.frame`), so the micro model learns one model per question for every person."""
        choices = {e.key: e.description() for e in self.settings.emotions}
        choices["none"] = "nothing in particular"
        return [
            Score("mood_change", "How did this move the assistant's own mood, from the assistant's side? Who "
                                 "started it is said at the top. Being annoyed at the user does not lower it; only "
                                 "aching for them, worry or sadness does.",
                  {"-2": "clearly worse", "-1": "a little worse", "0": "no real change", "1": "a little better",
                   "2": "clearly better"}),
            Choice("feeling", "The assistant's strongest feeling after this.", choices),
        ]

    async def ajudge(self, subject: str, exchange: str | Sequence[tuple[str, str]], *, source: str = "user",
                     user: str = "the user", decider: Chain | None = None) -> MoodEvent | None:
        """Judge one exchange and move the mood; returns the recorded change, or None when nothing changed.

        `decider` replaces the mood's own chain for this call (for hosts whose model handle belongs to one
        request)."""
        decider = decider or self.decider
        if source in self.settings.skip or decider is None:
            return None
        framed = exchanges.frame(exchange, source=source, user=user, assistant=self.name)
        answers = await decider.adecide(framed, self.questions())
        return self.apply_answers(subject, answers, exchange, source=source, user=user)

    def apply_answers(self, subject: str, answers, exchange, *, source: str = "user",
                      user: str = "the user") -> MoodEvent | None:
        """Move the mood from the judge's answers to `questions()` (other answers are ignored)."""
        s = self.settings
        if source in s.skip:
            return None
        exchange = exchanges.as_text(exchange)
        change, feeling = answers.get("mood_change"), answers.get("feeling")
        if change is None and feeling is None:
            return None
        reason = (change.reason if change else "") or (feeling.reason if feeling else "")
        if not reason and feeling is not None and feeling.choice != "none":
            reason = self._reason(feeling.choice, exchange, source, user)
        return self.apply(subject, delta=change.mean(LEVELS) * s.step if change else 0.0,
                          emotions=self._bumps(feeling), reason=reason,
                          confidence=_confidence(change, feeling), source=source,
                          judge="+".join(sorted({a.by for a in (change, feeling) if a is not None})))

    def judge(self, subject: str, exchange, **options) -> MoodEvent | None:
        """`ajudge` for code without an event loop."""
        return run(self.ajudge(subject, exchange, **options))

    def apply(self, subject: str, *, delta: float = 0.0, emotions: Mapping[str, float] | None = None,
              reason: str = "", confidence: float = 1.0, source: str = "manual",
              judge: str = "manual") -> MoodEvent | None:
        """Move the mood directly (hosts with their own judge use this); same guardrails as `judge`."""
        texts.required(subject, "subject")
        s = self.settings
        emotions = {key: float(value) for key, value in (emotions or {}).items() if value}
        if not all(math.isfinite(value) for value in [float(delta), float(confidence), *emotions.values()]):
            raise ValueError("a mood change, its feelings and its confidence are finite numbers")
        weight = s.weights.get(source, 1.0)
        delta *= weight
        emotions = {key: value * weight for key, value in emotions.items()}
        lowering = {e.key for e in s.emotions if e.lowers}
        if delta < 0:
            strongest = max(emotions, key=emotions.get) if emotions else None
            if strongest not in lowering:
                delta = 0.0
        if abs(delta) < 0.5 and all(value < 1.0 for value in emotions.values()):
            return None
        with self.store.transaction():  # read and write together, so concurrent judgements never lose one
            now = self.clock()
            state = self.state(subject, now)
            value = min(s.ceiling, max(s.floor, state.value + delta))
            mixed = dict(state.emotions)
            for key, amount in emotions.items():
                mixed[key] = min(100.0, mixed.get(key, 0.0) + amount)
            mixed = {key: round(amount, 2) for key, amount in mixed.items() if amount >= 0.5}
            cursor = self.store.execute(
                "insert into mood_events (space, subject, at, delta, value, emotions, reason, confidence, source, "
                "judge) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.space, subject, now, round(value - state.value, 2), round(value, 2), dumps(emotions),
                 texts.clip(reason, 200), round(confidence, 3), source, judge))
            event = cursor.lastrowid
            self.store.execute(
                "insert into moods (space, subject, value, emotions, updated_at, last_event) values (?, ?, ?, ?, ?, ?)"
                " on conflict(space, subject) do update set value = excluded.value, emotions = excluded.emotions, "
                "updated_at = excluded.updated_at, last_event = excluded.last_event",
                (self.space, subject, value, dumps(mixed), now, event))
        return MoodEvent(event, now, value - state.value, emotions, reason, confidence, source, judge, value)

    def reset(self, subject: str) -> None:
        """Back to baseline with no feelings and an empty timeline."""
        with self.store.transaction():
            self.store.execute("delete from moods where space = ? and subject = ?", (self.space, subject))
            self.store.execute("delete from mood_events where space = ? and subject = ?", (self.space, subject))

    # ---- moving between files ------------------------------------------------------------------------
    def export_rows(self) -> dict:
        def table(name: str) -> list[dict]:
            return [dict(row) for row in self.store.rows(f"select * from {name} where space = ? order by rowid",
                                                          (self.space,))]
        return {"moods": table("moods"), "mood_events": table("mood_events")}

    def import_rows(self, moods=(), events=()) -> None:
        """Add exported moods and timelines to this space, held to the mood's rules: values within the floor and
        ceiling, feelings as intensities 0-100, times in seconds; a row without a subject is skipped, and so is an
        event the timeline already has (importing an export twice adds it once). A mood comes without its links to
        events (nothing new is told)."""
        s, now = self.settings, self.clock()
        with self.store.transaction():
            for row in moods:
                subject = _subject(row)
                if subject is not None:
                    self.store.execute(
                        "insert or replace into moods (space, subject, value, emotions, updated_at, last_event, "
                        "told_event) values (?, ?, ?, ?, ?, null, null)",
                        (self.space, subject, _number(row.get("value"), s.baseline, s.floor, s.ceiling),
                         dumps(_feelings(row.get("emotions"))), _moment(row.get("updated_at"), now)))
            for row in events:
                subject = _subject(row)
                if subject is None:
                    continue
                event = (self.space, subject, _moment(row.get("at"), now), _number(row.get("delta"), 0.0, -100, 100),
                         _number(row.get("value"), s.baseline, s.floor, s.ceiling),
                         dumps(_feelings(row.get("emotions"))),
                         texts.clip(row["reason"], 200) if isinstance(row.get("reason"), str) else "",
                         _number(row.get("confidence"), 0.0, 0.0, 1.0), _word(row.get("source"), "import"),
                         _word(row.get("judge"), "import"))
                columns = "space, subject, at, delta, value, emotions, reason, confidence, source, judge"
                if self.store.row(f"select 1 from mood_events where ({columns}) = (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                  event) is None:
                    self.store.execute(f"insert into mood_events ({columns}) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                       event)

    # ---- inside --------------------------------------------------------------------------------------
    def _state(self, value: float, emotions: dict[str, float], updated_at: float | None) -> MoodState:
        for floor, face in FACES:
            if round(value) >= floor:
                return MoodState(value, emotions, face, updated_at)
        return MoodState(value, emotions, FACES[-1][1], updated_at)

    def _bumps(self, feeling: Answer | None) -> dict[str, float]:
        if feeling is None:
            return {}
        known = {e.key for e in self.settings.emotions}
        return {key: self.settings.gain * p for key, p in feeling.probabilities.items() if key in known and p >= 0.15}

    def _reason(self, key: str, exchange: str, source: str, user: str) -> str:
        emotion = {e.key: e for e in self.settings.emotions}.get(key)
        if emotion is None:
            return ""
        feeling = emotion.label(self.lang)
        if source == "speak-up":
            return say(self.lang, "mood.reason_reached", user=user, feeling=feeling)
        said = ""
        for line in reversed(exchange.splitlines()):
            if line.startswith(f"{user}:"):
                said = texts.clip(line.split(":", 1)[1].strip(), 40)  # one quoted line, never more
                break
        if said:
            return say(self.lang, "mood.reason", user=user, said=said, feeling=feeling)
        return say(self.lang, "mood.reason_plain", feeling=feeling)


def _subject(row) -> str | None:
    subject = row.get("subject") if isinstance(row, dict) else None
    return subject if isinstance(subject, str) and subject.strip() else None


def _number(value, default: float, low: float, high: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, value)) if math.isfinite(value) else default


def _moment(value, default: float) -> float:
    found = dates.seconds(value)
    return default if found is None else found


def _word(value, default: str) -> str:
    return texts.clip(value, 40) or default if isinstance(value, str) else default


def _feelings(value) -> dict[str, float]:
    """Feelings as stored: a JSON object (or a dict) of intensities, each kept within 0-100."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            value = {}
    if not isinstance(value, dict):
        return {}
    found = {str(key)[:40]: _number(amount, 0.0, 0.0, 100.0) for key, amount in value.items()}
    return {key: amount for key, amount in found.items() if amount > 0}


def _confidence(change: Answer | None, feeling: Answer | None) -> float:
    if feeling is not None and feeling.choice != "none":
        return feeling.confidence
    return change.confidence if change is not None else 0.0
