"""Small judgements (yes/no, pick one, rate on a scale) answered by the best tier that can, falling through.

    chain = Chain(Luna(), Micro(store), Prompt(complete))
    answers = await chain.adecide(text, [Predicate("remember", "The user shared something worth remembering.")])
    answers["remember"].probability            # or chain.decide(…) without an event loop

Tiers are tried in order. A tier may answer some questions and abstain on the rest (the micro model abstains
until it has learned a question well), or fail outright (no key, network down); whatever is left goes to the
next tier. A tier with a `learn` method learns from every answer a tier above it gave, which is how the micro
model is trained: by watching Luna. Leave any tier out and the rest still work. A tier is anything with a `name`
and an async `adecide(input, questions)`; a Chain is one too, so chains nest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol, Sequence, Union

from ..providers import Unavailable, run

log = logging.getLogger("mneme_llm.decide")


def _pairs(items) -> tuple[tuple[str, str], ...]:
    if isinstance(items, Mapping):
        return tuple((str(key), str(value)) for key, value in items.items())
    return tuple((item, "") if isinstance(item, str) else (str(item[0]), str(item[1])) for item in items)


@dataclass(frozen=True)
class Predicate:
    """Is this statement true of the input? Answered with a probability."""
    name: str
    instructions: str
    type = "predicate"

    @property
    def labels(self) -> tuple[str, ...]:
        return ("true", "false")


@dataclass(frozen=True)
class Choice:
    """Which one option fits the input best? `options` is {value: description} or a list of values."""
    name: str
    instructions: str
    options: tuple[tuple[str, str], ...]
    type = "choice"

    def __init__(self, name: str, instructions: str, options):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "instructions", instructions)
        object.__setattr__(self, "options", _pairs(options))
        if len(self.options) < 2:
            raise ValueError("a choice needs at least two options")

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(value for value, _ in self.options)


@dataclass(frozen=True)
class Score:
    """Where on an ordered scale does the input sit? `levels` is {label: description}, lowest first."""
    name: str
    instructions: str
    levels: tuple[tuple[str, str], ...]
    type = "score"

    def __init__(self, name: str, instructions: str, levels):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "instructions", instructions)
        object.__setattr__(self, "levels", _pairs(levels))
        if len(self.levels) < 2:
            raise ValueError("a score needs at least two levels")

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(label for label, _ in self.levels)


Question = Union[Predicate, Choice, Score]


@dataclass(frozen=True)
class Answer:
    """One question's answer: a probability for every label, how sure, and which tier said so."""
    name: str
    type: str
    probabilities: dict[str, float]
    confidence: float
    by: str
    reason: str = ""

    @property
    def choice(self) -> str:
        """The most likely label ("true"/"false" for a predicate)."""
        return max(self.probabilities, key=self.probabilities.get)

    @property
    def probability(self) -> float:
        """For a predicate: how likely it is true."""
        return self.probabilities.get("true", 0.0)

    def mean(self, values: Mapping[str, float] | None = None) -> float:
        """The expected value over labels; labels are read as numbers unless `values` maps them."""
        total = 0.0
        for label, p in self.probabilities.items():
            total += p * (values[label] if values is not None else float(label))
        return total


def normalized(probabilities: Mapping[str, float], labels: Sequence[str]) -> dict[str, float]:
    """Probabilities for exactly `labels`, summing to 1 (uniform if nothing usable was given)."""
    clean = {label: max(0.0, float(probabilities.get(label, 0.0) or 0.0)) for label in labels}
    total = sum(clean.values())
    if total <= 0:
        return {label: 1 / len(labels) for label in labels}
    return {label: value / total for label, value in clean.items()}


class Decider(Protocol):
    name: str

    async def adecide(self, input: str, questions: Sequence[Question]) -> dict[str, Answer]:
        """Answers for the questions this tier is willing to answer; raising means "none of them"."""


@dataclass
class TierStats:
    answered: int = 0
    abstained: int = 0
    failed: int = 0
    last_error: str = ""


@dataclass
class Chain:
    """Deciders in order of preference; each question goes to the first that answers it."""
    tiers: list = field(default_factory=list)
    stats: dict[str, TierStats] = field(default_factory=dict)
    name: str = "chain"

    def __init__(self, *tiers, name: str = "chain"):
        self.name = name
        self.tiers = [tier for tier in tiers if tier is not None]
        self.stats = {tier.name: TierStats() for tier in self.tiers}

    async def adecide(self, input: str, questions: Iterable[Question]) -> dict[str, Answer]:
        """Answers for every question some tier could answer (a question no tier answers is left out)."""
        pending = list(questions)
        answers: dict[str, Answer] = {}
        teachers: list[tuple[int, Answer, Question]] = []
        for rank, tier in enumerate(self.tiers):
            if not pending:
                break
            stats = self.stats.setdefault(tier.name, TierStats())
            try:
                got = await tier.adecide(input, pending)
            except Exception as error:  # one tier failing is exactly what the next one is for
                stats.failed += 1
                stats.last_error = f"{type(error).__name__}: {error}"[:300]
                log.info("decider %s failed: %s", tier.name, stats.last_error)
                continue
            remaining = []
            for question in pending:
                answer = got.get(question.name)
                if answer is None:
                    stats.abstained += 1
                    remaining.append(question)
                else:
                    stats.answered += 1
                    answers[question.name] = answer
                    teachers.append((rank, answer, question))
            pending = remaining
        for rank, answer, question in teachers:
            for tier in self.tiers[rank + 1:]:
                learn = getattr(tier, "learn", None)
                if learn is not None:
                    try:
                        learn(input, question, answer)
                    except Exception:  # learning is a bonus; never let it break a decision
                        log.exception("decider %s could not learn", tier.name)
        return answers

    def decide(self, input: str, questions: Iterable[Question]) -> dict[str, Answer]:
        """`adecide` for code without an event loop."""
        return run(self.adecide(input, questions))

    def learn(self, input: str, question: Question, answer: Answer) -> None:
        """As a tier of another chain: an answer from above teaches every tier of this one that learns."""
        for tier in self.tiers:
            learn = getattr(tier, "learn", None)
            if learn is not None:
                learn(input, question, answer)

    def report(self) -> dict:
        report = {name: vars(stats).copy() for name, stats in self.stats.items()}
        for tier in self.tiers:
            describe = getattr(tier, "report", None)
            if describe is not None:
                report[tier.name]["details"] = describe()
        return report


def fit(text: str, limit: int) -> str:
    """`text` within `limit` characters for a judge: the opening (where who-is-who is said) and the end (the
    newest words) are kept, the middle is cut."""
    if len(text) <= limit:
        return text
    head = min(600, limit // 3)
    tail = limit - head - 5  # (the marker takes 5)
    return text[:head] + "\n[…]\n" + text[-tail:] if tail > 0 else text[:max(0, limit)]


from .luna import Luna  # noqa: E402  (the tiers use the types above)
from .prompt import Prompt  # noqa: E402

__all__ = ["Answer", "Chain", "Choice", "Decider", "Luna", "Predicate", "Prompt", "Question", "Score",
           "Unavailable", "fit", "normalized", "run"]
