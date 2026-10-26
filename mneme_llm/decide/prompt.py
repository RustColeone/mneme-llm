"""Tier 3: any chat model you already have, asked for a small JSON verdict (the way dsh-feiyu-mood judges).

You pass `complete(system, user) -> str` (or an async function returning str): DeepSeek, Claude, a local model,
anything. It is slower and costs output tokens, but it never needs a second provider and it can also say why
(each answer may carry a short `reason`). How it is asked is `system` (`prompts.PROMPTS["judge"]` by default).
"""

from __future__ import annotations

from typing import Sequence

from ..prompts import PROMPTS
from ..providers import Complete, ask, json_in
from . import Answer, Question, fit, normalized


class Prompt:
    name = "prompt"

    def __init__(self, complete: Complete | None, *, system: str = PROMPTS["judge"], max_input: int = 12000):
        self.complete, self.system, self.max_input = complete, system, max_input
        self.calls = 0

    def message(self, input: str, questions: Sequence[Question]) -> str:
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

    def parse(self, reply: str, questions: Sequence[Question]) -> dict[str, Answer]:
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
                    answers[question.name] = Answer(question.name, "predicate", {"true": p, "false": 1 - p},
                                                    max(p, 1 - p), self.name, reason)
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
            answers[question.name] = Answer(question.name, question.type, probabilities, confidence, self.name, reason)
        return answers

    async def adecide(self, input: str, questions: Sequence[Question]) -> dict[str, Answer]:
        reply = await ask(self.complete, self.system, self.message(input, questions))
        self.calls += 1
        return self.parse(reply, questions)

    def report(self) -> dict:
        return {"calls": self.calls}
