"""Meaning: finding notes by what they mean, not only by the words they share, in three tiers that fall through.

    1. embeddings   a provider turns text into vectors: `OpenAIEmbeddings()` (text-embedding-3-small at 256
                    dimensions, with OPENAI_API_KEY), or any function you give (`Embeddings(fn, name=...)`)
    2. micro        optional and removable: word centroids learned from tier 1's vectors, so a query can be
                    placed among the notes offline once enough text has been seen; abstains on unknown words
    3. unify        your own chat model writes each note once in one language of your choice (English by
                    default) and translates a query written in another script, so word matching works across
                    languages

Tiers 1 and 2 give a vector for the query, compared with the vectors tier 1 stored for the notes; tier 3 adds
words to the matching. With no tier available, recall is word matching alone, as before. Vectors are stored per
embedder (`name`), so changing the provider never compares vectors from two different models.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
from array import array
from typing import Awaitable, Callable, Protocol, Sequence, Union

from ..decide import Unavailable

log = logging.getLogger("mneme_llm.meaning")
Vector = list


class Embedder(Protocol):
    name: str  # identifies the model and its settings; vectors from different names are never compared

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        """One vector per text, in order; raising means this tier is unavailable."""


# ---- vectors ----------------------------------------------------------------------------------------
def normalize(vector: Sequence[float]) -> Vector:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def pack(vector: Sequence[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> Vector:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Of two normalized vectors."""
    return sum(x * y for x, y in zip(a, b))


# ---- tier 1: providers ------------------------------------------------------------------------------
class OpenAIEmbeddings:
    """OpenAI's embeddings API: `text-embedding-3-small` at 256 dimensions costs $0.02 per million tokens and
    places Chinese and English texts about the same thing close together."""

    def __init__(self, api_key: str | None = None, *, model: str = "text-embedding-3-small", dimensions: int = 256,
                 base_url: str = "https://api.openai.com/v1", timeout: float = 15.0):
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.model, self.dimensions, self.base_url, self.timeout = model, dimensions, base_url.rstrip("/"), timeout
        self.name = f"openai:{model}:{dimensions}"
        self.input_tokens = 0

    def _post(self, texts: list[str]) -> dict:
        body = {"model": self.model, "input": texts, "dimensions": self.dimensions}
        request = urllib.request.Request(f"{self.base_url}/embeddings", data=json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {self.api_key}",
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise Unavailable(f"embeddings API answered {error.code}: "
                              f"{error.read().decode('utf-8', 'replace')[:200]}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise Unavailable(f"embeddings API unreachable: {error}") from None

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        if not self.api_key:
            raise Unavailable("no OpenAI key for embeddings")
        payload = await asyncio.to_thread(self._post, [text[:8000] or " " for text in texts])
        self.input_tokens += int(payload.get("usage", {}).get("prompt_tokens", 0) or 0)
        ordered = sorted(payload["data"], key=lambda item: item["index"])
        return [normalize(item["embedding"]) for item in ordered]

    def report(self) -> dict:
        return {"input_tokens": self.input_tokens, "dollars": round(self.input_tokens * 0.02 / 1_000_000, 6)}


EmbedFunction = Callable[[list], Union[list, Awaitable[list]]]


class Embeddings:
    """Any embedding function (sync or async, list of texts → list of vectors): a local model, Ollama, Gemini…
    Give it a `name` that changes when the model does."""

    def __init__(self, function: EmbedFunction, name: str):
        self.function, self.name = function, name

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        if inspect.iscoroutinefunction(self.function):
            vectors = await self.function(list(texts))
        else:
            vectors = await asyncio.to_thread(self.function, list(texts))
            if inspect.isawaitable(vectors):
                vectors = await vectors
        if len(vectors) != len(texts):
            raise Unavailable(f"{self.name} returned {len(vectors)} vectors for {len(texts)} texts")
        return [normalize(vector) for vector in vectors]


# ---- the tiers together -----------------------------------------------------------------------------
class Found:
    """What the tiers made of a query: a vector (from `tier`), and words to add to the matching."""

    def __init__(self, vector: Vector | None = None, tier: str = "", words: str = ""):
        self.vector, self.tier, self.words = vector, tier, words


class Meaning:
    """The tiers for one store. Each may be None; any that fails passes the query on to the next."""

    BATCH = 64
    REST_S = 60.0  # after the provider fails, skip it this long instead of waiting on it every time

    def __init__(self, store, embedder: Embedder | None = None, micro=None, unify=None):
        self.store, self.embedder, self.micro, self.unify = store, embedder, micro, unify
        self.failures: dict[str, str] = {}
        self._resting_until = 0.0

    def _embedder_up(self) -> bool:
        return self.embedder is not None and time.monotonic() >= self._resting_until

    def _embedder_failed(self, error: Exception) -> None:
        self.failures["embeddings"] = f"{type(error).__name__}: {error}"[:200]
        self._resting_until = time.monotonic() + self.REST_S
        log.info("embeddings unavailable for %.0f s: %s", self.REST_S, self.failures["embeddings"])

    @property
    def name(self) -> str:
        return self.embedder.name if self.embedder is not None else ""

    async def query(self, text: str, *, complete=None) -> Found:
        """The best the tiers can do for a query (an empty `Found` when none can). `complete` gives the unify
        tier a chat model for this call."""
        if self._embedder_up():
            try:
                vector = (await self.embedder.embed([text]))[0]
                if self.micro is not None:
                    self.micro.learn([(text, vector)])
                return Found(vector, "embeddings")
            except Exception as error:
                self._embedder_failed(error)
        if self.micro is not None:
            vector = self.micro.vector(text)
            if vector is not None:
                return Found(vector, "micro")
        if self.unify is not None and self.unify.needs_translation(text):
            try:
                return Found(None, "unify", await self.unify.translate(text, complete=complete))
            except Exception as error:
                self.failures["unify"] = f"{type(error).__name__}: {error}"[:200]
        return Found()

    async def prepare_vectors(self, notes) -> int:
        """Embed the notes that have no vector from this embedder yet (in batches); returns how many were added."""
        if not self._embedder_up() or not notes:
            return 0
        have: set[int] = set()
        ids = [note.id for note in notes]
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            rows = self.store.rows(f"select memory_id from vectors where embedder = ? and memory_id in "
                                   f"({', '.join('?' * len(chunk))})", (self.name, *chunk))
            have.update(row["memory_id"] for row in rows)
        missing = [note for note in notes if note.id not in have]
        added = 0
        for start in range(0, len(missing), self.BATCH):
            batch = missing[start:start + self.BATCH]
            try:
                vectors = await self.embedder.embed([note.text for note in batch])
            except Exception as error:
                self._embedder_failed(error)
                break
            with self.store.transaction():
                for note, vector in zip(batch, vectors):
                    self.store.execute("insert or replace into vectors (memory_id, embedder, vector) values (?, ?, ?)",
                                       (note.id, self.name, pack(vector)))
            if self.micro is not None:
                self.micro.learn([(note.text, vector) for note, vector in zip(batch, vectors)])
            added += len(batch)
        return added

    async def prepare_glosses(self, notes, *, complete=None) -> int:
        """Write a gloss for the notes that have none (only needed when word matching is all there is)."""
        if self.unify is None:
            return 0
        missing = [note for note in notes if not note.gloss]
        added = 0
        for start in range(0, len(missing), self.BATCH):
            batch = missing[start:start + self.BATCH]
            try:
                glosses = await self.unify.gloss([note.text for note in batch], complete=complete)
            except Exception as error:
                self.failures["unify"] = f"{type(error).__name__}: {error}"[:200]
                break
            with self.store.transaction():
                for note, gloss in zip(batch, glosses):
                    self.store.execute("update memories set gloss = ?, terms = null where id = ?", (gloss, note.id))
            added += len(batch)
        return added

    def vectors(self, ids: Sequence[int]) -> dict[int, Vector]:
        if not ids or not self.name:
            return {}
        found = {}
        for start in range(0, len(ids), 500):
            chunk = list(ids[start:start + 500])
            rows = self.store.rows(f"select memory_id, vector from vectors where embedder = ? and memory_id in "
                                   f"({', '.join('?' * len(chunk))})", (self.name, *chunk))
            found.update({row["memory_id"]: unpack(row["vector"]) for row in rows})
        return found

    def report(self) -> dict:
        report = {"embedder": self.name or None, "micro": None, "unify": None, "failures": dict(self.failures)}
        if self.embedder is not None and hasattr(self.embedder, "report"):
            report["embeddings"] = self.embedder.report()
        if self.micro is not None:
            report["micro"] = self.micro.report()
        if self.unify is not None:
            report["unify"] = {"language": self.unify.language, "calls": self.unify.calls}
        return report


__all__ = ["Embedder", "Embeddings", "Found", "Meaning", "OpenAIEmbeddings", "cosine", "normalize", "pack",
           "unpack"]
