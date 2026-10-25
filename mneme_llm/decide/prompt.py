"""Tier 3: any chat model you already have, asked for a small JSON verdict (the way dsh-feiyu-mood judges).

You pass `complete(system, user) -> str` (or an async function returning str): DeepSeek, Claude, a local model,
anything. It is slower and costs output tokens, but it never needs a second provider and it can also say why
(each answer may carry a short `reason`).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Awaitable, Callable, Sequence, Union

from . import Answer, Question, Unavailable, normalized

Complete = Callable[[str, str], Union[str, Awaitable[str]]]

SYSTEM = """You judge a piece of text and answer questions about it. Reply with only one JSON object, no prose,
with one entry per question name:
- yes/no question: {"probability": <0..1 that it is true>}
- choice: {"choice": "<one of the listed values>", "confidence": <0..1>}
- score: {"level": "<one of the listed labels>", "confidence": <0..1>}
Any entry may add "reason": one short sentence. Use only the listed values and labels."""


class Prompt:
    name = "prompt"

    def __init__(self, complete: Complete | None, *, system: str = SYSTEM, max_input: int = 12000):
        self.complete, self.system, self.max_input = complete, system, max_input
        self.calls = 0

    def message(self, input: str, questions: Sequence[Question]) -> str:
        lines = ["TEXT:", input[-self.max_input:], "", "QUESTIONS:"]
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
        found = re.search(r"\{.*\}", reply, re.S)
        if not found:
            return {}
        try:
            data = json.loads(found.group(0))
        except json.JSONDecodeError:
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
            rest = (1 - confidence) / (len(labels) - 1)
            probabilities = normalized({label: confidence if label == picked else rest for label in labels}, labels)
            answers[question.name] = Answer(question.name, question.type, probabilities, confidence, self.name, reason)
        return answers

    async def decide(self, input: str, questions: Sequence[Question]) -> dict[str, Answer]:
        if self.complete is None:
            raise Unavailable("no completion function given")
        message = self.message(input, questions)
        if inspect.iscoroutinefunction(self.complete):
            reply = await self.complete(self.system, message)
        else:
            reply = await asyncio.to_thread(self.complete, self.system, message)
            if inspect.isawaitable(reply):
                reply = await reply
        self.calls += 1
        return self.parse(str(reply or ""), questions)

    def report(self) -> dict:
        return {"calls": self.calls}
