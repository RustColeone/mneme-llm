"""Tier 1: OpenAI's Decisions API (GPT-6 Luna). Fast (about 0.2-0.4 s), priced on input only, no text output.

    POST {base_url}/decisions  {"model": "gpt-6-luna", "input": "...", "questions": [...]}

Predicates come back as a probability; choices and scores as a probability per option or level plus a
confidence. Without a key (argument or OPENAI_API_KEY) this tier reports itself unavailable and the chain moves on.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Sequence

from . import Answer, Question, Unavailable, normalized


class Luna:
    name = "luna"

    def __init__(self, api_key: str | None = None, *, model: str = "gpt-6-luna",
                 base_url: str = "https://api.openai.com/v1", timeout: float = 10.0, max_input: int = 60000):
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.model, self.base_url, self.timeout, self.max_input = model, base_url.rstrip("/"), timeout, max_input
        self.input_tokens = 0
        self.calls = 0

    def body(self, input: str, questions: Sequence[Question]) -> dict:
        wire = []
        for question in questions:
            item = {"name": question.name, "type": question.type, "instructions": question.instructions}
            if question.type == "choice":
                item["choices"] = [{"value": value, "description": text} if text else {"value": value}
                                   for value, text in question.options]
            elif question.type == "score":
                item["levels"] = [{"label": label, "description": text} if text else {"label": label}
                                  for label, text in question.levels]
            wire.append(item)
        return {"model": self.model, "input": input[-self.max_input:], "questions": wire}

    def parse(self, payload: dict, questions: Sequence[Question]) -> dict[str, Answer]:
        by_name = {question.name: question for question in questions}
        answers = {}
        for item in payload.get("answers", []):
            question = by_name.get(item.get("name"))
            if question is None:
                continue
            if question.type == "predicate":
                p = min(1.0, max(0.0, float(item.get("probability", 0.5))))
                answers[question.name] = Answer(question.name, "predicate", {"true": p, "false": 1 - p},
                                                max(p, 1 - p), self.name)
                continue
            key = "value" if question.type == "choice" else "label"
            given = {str(entry.get(key)): entry.get("probability", 0.0) for entry in item.get("probabilities", [])}
            probabilities = normalized(given, question.labels)
            confidence = float(item.get("confidence", max(probabilities.values())))
            answers[question.name] = Answer(question.name, question.type, probabilities, confidence, self.name)
        return answers

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(f"{self.base_url}/decisions", data=json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {self.api_key}",
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise Unavailable(f"decisions API answered {error.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise Unavailable(f"decisions API unreachable: {error}") from None

    async def decide(self, input: str, questions: Sequence[Question]) -> dict[str, Answer]:
        if not self.api_key:
            raise Unavailable("no OpenAI key for the decisions API")
        payload = await asyncio.to_thread(self._post, self.body(input, questions))
        self.calls += 1
        self.input_tokens += int(payload.get("usage", {}).get("input_tokens", 0) or 0)
        return self.parse(payload, questions)

    def report(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens,
                "dollars": round(self.input_tokens * 0.10 / 1_000_000, 6)}
