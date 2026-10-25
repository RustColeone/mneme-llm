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
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from . import text as texts
from .decide import Answer, Chain, Choice, Score
from .i18n import say
from .store import Store, dumps


@dataclass(frozen=True)
class Emotion:
    key: str
    en: str
    zh: str
    lowers: bool = False  # may this feeling pull her mood down?


EMOTIONS = (
    Emotion("happy", "happy", "开心"),
    Emotion("calm", "at ease", "踏实"),
    Emotion("sweet", "sweet on them", "甜蜜"),
    Emotion("tender", "aching for them", "心疼", lowers=True),
    Emotion("worried", "worried", "担心", lowers=True),
    Emotion("sad", "sad", "难过", lowers=True),
    Emotion("jealous", "jealous", "吃醋"),
)
FACES = ((80, "great", "欢喜"), (62, "good", "开心"), (42, "ok", "一般"), (25, "worry", "心疼"), (0, "sad", "难过"))
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
    face: str
    face_zh: str
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
        names = {e.key: self._emotion_name(e) for e in self.settings.emotions}
        feelings = say(self.lang, "mood.separator").join(f"{names.get(key, key)} {round(value)}"
                                                         for key, value in state.strongest())
        line = say(self.lang, "mood.line", value=round(state.value),
                   face=state.face_zh if self.lang == "zh" else state.face)
        return line + (say(self.lang, "mood.feelings", feelings=feelings) if feelings else "")

    def news(self, subject: str, *, mark: bool = True) -> str | None:
        """The newest confident change, once (None if there is nothing new to tell or telling is off)."""
        s = self.settings
        if s.tell == "off":
            return None
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
        judged text; see `frame`), so the micro model learns one model per question for every person."""
        choices = {e.key: f"{e.en} ({e.zh})" for e in self.settings.emotions}
        choices["none"] = "nothing in particular"
        return [
            Score("mood_change", "How did this move the assistant's own mood, from the assistant's side? Who "
                                 "started it is said at the top. Being annoyed at the user does not lower it; only "
                                 "aching for them, worry or sadness does.",
                  {"-2": "clearly worse", "-1": "a little worse", "0": "no real change", "1": "a little better",
                   "2": "clearly better"}),
            Choice("feeling", "The assistant's strongest feeling after this.", choices),
        ]

    def frame(self, exchange, source: str, user: str) -> str:
        """The text the judge reads: who is who and who started it, then the exchange."""
        exchange = exchange if isinstance(exchange, str) else "\n".join(f"{who}: {said}" for who, said in exchange)
        started = {"user": f"{user} is talking to {self.name}.",
                   "speak-up": f"{self.name} reached out to {user} on their own, because they wanted to (not as "
                               "a task).",
                   "duty": f"{self.name} is doing a scheduled task."}.get(source, "")
        return f"[{started} The assistant is {self.name}; the user is {user}.]\n{exchange}"

    async def ajudge(self, subject: str, exchange: str | Sequence[tuple[str, str]], *, source: str = "user",
                     user: str = "the user", decider: Chain | None = None) -> MoodEvent | None:
        """Judge one exchange and move the mood; returns the recorded change, or None when nothing changed.

        `decider` replaces the mood's own chain for this call (for hosts whose model handle belongs to one
        request)."""
        decider = decider or self.decider
        if source in self.settings.skip or decider is None:
            return None
        answers = await decider.adecide(self.frame(exchange, source, user), self.questions())
        return self.apply_answers(subject, answers, exchange, source=source, user=user)

    def apply_answers(self, subject: str, answers, exchange, *, source: str = "user",
                      user: str = "the user") -> MoodEvent | None:
        """Move the mood from the judge's answers to `questions()` (other answers are ignored)."""
        s = self.settings
        if source in s.skip:
            return None
        exchange = exchange if isinstance(exchange, str) else "\n".join(f"{who}: {said}" for who, said in exchange)
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
        from .decide import run
        return run(self.ajudge(subject, exchange, **options))

    def apply(self, subject: str, *, delta: float = 0.0, emotions: Mapping[str, float] | None = None,
              reason: str = "", confidence: float = 1.0, source: str = "manual",
              judge: str = "manual") -> MoodEvent | None:
        """Move the mood directly (hosts with their own judge use this); same guardrails as `judge`."""
        s = self.settings
        emotions = {key: float(value) for key, value in (emotions or {}).items() if value}
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
        now = self.clock()
        state = self.state(subject, now)
        value = min(s.ceiling, max(s.floor, state.value + delta))
        mixed = dict(state.emotions)
        for key, amount in emotions.items():
            mixed[key] = min(100.0, mixed.get(key, 0.0) + amount)
        mixed = {key: round(amount, 2) for key, amount in mixed.items() if amount >= 0.5}
        with self.store.transaction():
            cursor = self.store.execute(
                "insert into mood_events (space, subject, at, delta, value, emotions, reason, confidence, source, judge)"
                " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    # ---- inside --------------------------------------------------------------------------------------
    def _state(self, value: float, emotions: dict[str, float], updated_at: float | None) -> MoodState:
        for floor, face, face_zh in FACES:
            if round(value) >= floor:
                return MoodState(value, emotions, face, face_zh, updated_at)
        return MoodState(value, emotions, FACES[-1][1], FACES[-1][2], updated_at)

    def _bumps(self, feeling: Answer | None) -> dict[str, float]:
        if feeling is None:
            return {}
        known = {e.key for e in self.settings.emotions}
        return {key: self.settings.gain * p for key, p in feeling.probabilities.items() if key in known and p >= 0.15}

    def _emotion_name(self, emotion: Emotion) -> str:
        return emotion.zh if self.lang == "zh" else emotion.en

    def _reason(self, key: str, exchange: str, source: str, user: str) -> str:
        emotion = {e.key: e for e in self.settings.emotions}.get(key)
        if emotion is None:
            return ""
        feeling = self._emotion_name(emotion)
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


def _confidence(change: Answer | None, feeling: Answer | None) -> float:
    if feeling is not None and feeling.choice != "none":
        return feeling.confidence
    return change.confidence if change is not None else 0.0
