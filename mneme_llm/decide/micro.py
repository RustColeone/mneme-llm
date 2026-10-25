"""Tier 2 (optional, removable): a tiny local model that learns each question by watching the tier above.

Nothing to download or install. Each question gets its own logistic/softmax model over hashed text features
(the same terms memory search uses), trained online on the probabilities Luna gave, so it learns Luna's
judgement on *your* conversations. Before every lesson it guesses first; it starts answering only after
`min_examples` lessons and while its recent guesses agree with the teacher at least `min_agreement` of the time,
and then only when it is at least `min_confidence` sure. Until then it abstains and the question falls through.

Delete this file (or pass `micro=False`) and nothing else changes; its weights live in the `micro_models` table.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import zlib
from typing import Sequence

from .. import text as texts
from ..store import Store
from . import Answer, Question


def signature(question: Question) -> str:
    """Changing a question's wording or options gives it a new model (the old one is not reused)."""
    raw = "|".join([question.type, question.instructions, *question.labels])
    return f"{question.name}:{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


class _Model:
    def __init__(self, labels: Sequence[str], data: dict | None = None, examples: int = 0):
        self.labels = list(labels)
        data = data or {}
        self.bias = data.get("bias", [0.0] * len(self.labels))
        self.weights = {int(key): value for key, value in data.get("w", {}).items()}
        self.window: list[int] = data.get("window", [])
        self.examples = examples
        self.dirty = 0

    def predict(self, features: dict[int, float]) -> list[float]:
        scores = list(self.bias)
        for index, value in features.items():
            row = self.weights.get(index)
            if row is not None:
                for k, weight in enumerate(row):
                    scores[k] += weight * value
        top = max(scores)
        exps = [math.exp(score - top) for score in scores]
        total = sum(exps)
        return [value / total for value in exps]

    def update(self, features: dict[int, float], target: Sequence[float], rate: float) -> None:
        predicted = self.predict(features)
        step = rate / math.sqrt(1 + self.examples / 50)
        gradient = [p - t for p, t in zip(predicted, target)]
        for k, g in enumerate(gradient):
            self.bias[k] -= step * g
        for index, value in features.items():
            row = self.weights.setdefault(index, [0.0] * len(self.labels))
            for k, g in enumerate(gradient):
                row[k] -= step * g * value
        self.examples += 1
        self.dirty += 1

    def dump(self) -> str:
        return json.dumps({"bias": [round(b, 5) for b in self.bias], "window": self.window,
                           "w": {str(key): [round(w, 5) for w in row] for key, row in self.weights.items()}},
                          separators=(",", ":"))


class Micro:
    name = "micro"

    def __init__(self, store: Store, *, min_examples: int = 200, min_agreement: float = 0.85,
                 min_confidence: float = 0.8, window: int = 100, bits: int = 18, rate: float = 1.0,
                 save_every: int = 20):
        self.store = store
        self.min_examples, self.min_agreement, self.min_confidence = min_examples, min_agreement, min_confidence
        self.window, self.mask, self.rate, self.save_every = window, (1 << bits) - 1, rate, save_every
        self._models: dict[str, _Model] = {}

    # ---- the model's view of a text ------------------------------------------------------------------
    def features(self, input: str) -> dict[int, float]:
        terms = texts.terms(input)
        terms += [f"#len{min(6, len(input) // 80)}"]
        found: dict[int, float] = {}
        for term in terms:
            index = zlib.crc32(term.encode()) & self.mask
            found[index] = found.get(index, 0.0) + 1.0
        norm = math.sqrt(sum(value * value for value in found.values())) or 1.0
        return {index: value / norm for index, value in found.items()}

    def _model(self, question: Question) -> _Model:
        key = signature(question)
        model = self._models.get(key)
        if model is None:
            row = self.store.row("select * from micro_models where question = ?", (key,))
            if row is not None and json.loads(row["labels"]) == list(question.labels):
                model = _Model(question.labels, json.loads(row["weights"]), row["examples"])
            else:
                model = _Model(question.labels)
            self._models[key] = model
        return model

    def trusted(self, question: Question) -> bool:
        model = self._model(question)
        recent = model.window[-self.window:]
        return (model.examples >= self.min_examples and len(recent) >= min(self.window, self.min_examples)
                and sum(recent) / len(recent) >= self.min_agreement)

    # ---- the tier ------------------------------------------------------------------------------------
    async def decide(self, input: str, questions: Sequence[Question]) -> dict[str, Answer]:
        features = None
        answers = {}
        for question in questions:
            if not self.trusted(question):
                continue
            features = features or self.features(input)
            model = self._model(question)
            predicted = model.predict(features)
            confidence = max(predicted)
            if confidence < self.min_confidence:
                continue
            answers[question.name] = Answer(question.name, question.type, dict(zip(model.labels, predicted)),
                                            confidence, self.name)
        return answers

    def learn(self, input: str, question: Question, answer: Answer) -> None:
        """One lesson: guess, compare with the teacher's answer, then move toward it."""
        model = self._model(question)
        features = self.features(input)
        target = [answer.probabilities.get(label, 0.0) for label in model.labels]
        guess = model.predict(features)
        if question.type == "score":
            expected = sum(i * p for i, p in enumerate(guess))
            wanted = sum(i * p for i, p in enumerate(target))
            agreed = abs(expected - wanted) <= 0.5
        else:
            agreed = guess.index(max(guess)) == target.index(max(target))
        model.window = (model.window + [int(agreed)])[-self.window:]
        model.update(features, target, self.rate)
        if model.dirty >= self.save_every:
            self._save(signature(question), question, model)

    def flush(self) -> None:
        """Write every model with unsaved lessons (call before exiting; lessons since the last save are lost
        otherwise, which costs only a little training)."""
        for key, model in self._models.items():
            if model.dirty:
                self._save(key, None, model)

    def _save(self, key: str, question: Question | None, model: _Model) -> None:
        kind = question.type if question is not None else ""
        self.store.execute("insert into micro_models (question, kind, labels, weights, examples, updated_at) values "
                           "(?, ?, ?, ?, ?, ?) on conflict(question) do update set labels = excluded.labels, weights ="
                           " excluded.weights, examples = excluded.examples, updated_at = excluded.updated_at, kind ="
                           " case when excluded.kind = '' then micro_models.kind else excluded.kind end",
                           (key, kind, json.dumps(model.labels), model.dump(), model.examples, time.time()))
        model.dirty = 0

    def report(self) -> dict:
        found = {}
        for key, model in self._models.items():
            recent = model.window[-self.window:]
            found[key] = {"examples": model.examples,
                          "agreement": round(sum(recent) / len(recent), 3) if recent else None,
                          "trusted": model.examples >= self.min_examples and bool(recent)
                          and sum(recent) / len(recent) >= self.min_agreement}
        return found

    def reset(self, question: Question | None = None) -> None:
        """Forget what was learned (one question, or all)."""
        if question is None:
            self.store.execute("delete from micro_models")
            self._models.clear()
        else:
            self.store.execute("delete from micro_models where question = ?", (signature(question),))
            self._models.pop(signature(question), None)
