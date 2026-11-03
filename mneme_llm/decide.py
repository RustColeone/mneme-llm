"""Small judgements about a text (yes/no, pick one, rate on a scale), answered by your own chat model.

    answers = await Prompt(complete).adecide(text, [Predicate("remember", "The user shared something worth remembering.")])
    answers["remember"].probability

`complete(system, user) -> str` (or an async function returning str) is any chat model you already have: DeepSeek,
Claude, a local model. It is asked for a small JSON verdict, which costs output tokens but needs no second provider,
and each answer may carry a short `reason`. How it is asked is `system` (`prompts.PROMPTS["judge"]` by default).

A host with a judge of its own gives `Mneme` anything with an async `adecide(input, questions)` returning answers by
question name, in place of `Prompt`; a question it leaves out goes unanswered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .prompts import PROMPTS
from .providers import Complete, ask, json_in
from .text import fit


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


@dataclass(frozen=True)
class Answer:
    """One question's answer: a probability for every label, how sure, and who said so."""
    name: str
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


class Prompt:
    """Your chat model as a judge."""
    name = "prompt"

    def __init__(self, complete: Complete | None, *, system: str = PROMPTS["judge"], max_input: int = 12000):
        self.complete, self.system, self.max_input = complete, system, max_input

    def message(self, input: str, questions: Sequence) -> str:
        lines = ["TEXT:", fit(input, self.max_input), "", "QUESTIONS:"]
        for question in questions:
            if question.type == "predicate":
                lines.append(f'- "{question.name}" (yes/no): {question.instructions}')
            elif question.type == "choice":
                options = "; ".join(f"{value} = {text}" if text else value for value, text in question.options)
                lines.append(f'- "{question.name}" (choice): {question.instructions} Values: {options}')
            else:
                levels = "; ".join(f"{label} = {text}" if text else label for label, text in question.levels)
                lines.append(f'- "{question.name}" (score, lowest first): {question.instructions} Labels: {levels}')
        return "\n".join(lines)

    def parse(self, reply: str, questions: Sequence) -> dict[str, Answer]:
        data = json_in(reply, "{")
        if not isinstance(data, dict):
            return {}
        answers = {}
        for question in questions:
            item = data.get(question.name)
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason", ""))[:300]
            try:
                if question.type == "predicate":
                    p = min(1.0, max(0.0, float(item["probability"])))
                    answers[question.name] = Answer(question.name, {"true": p, "false": 1 - p}, max(p, 1 - p),
                                                    self.name, reason)
                    continue
                picked = str(item["choice" if question.type == "choice" else "level"])
                confidence = min(1.0, max(0.0, float(item.get("confidence", 0.7))))
            except (KeyError, TypeError, ValueError):
                continue
            labels = question.labels
            if picked not in labels:
                continue
            # The picked label stays the most likely even when the model is unsure (a share of at least
            # 2 / (n + 1) puts it above every other); the stated confidence is kept as it was.
            share = max(confidence, 2 / (len(labels) + 1))
            rest = (1 - share) / (len(labels) - 1)
            probabilities = normalized({label: share if label == picked else rest for label in labels}, labels)
            answers[question.name] = Answer(question.name, probabilities, confidence, self.name, reason)
        return answers

    async def adecide(self, input: str, questions: Sequence) -> dict[str, Answer]:
        return self.parse(await ask(self.complete, self.system, self.message(input, questions)), questions)
