"""Meaning: finding notes by what they mean, not only by the words they share, in three tiers that fall through.

    1. embeddings   a provider turns text into vectors: `OpenAIEmbeddings()` (text-embedding-3-small at 256
                    dimensions, with OPENAI_API_KEY), or any function you give (`Embeddings(fn, name=...)`)
    2. micro        optional and removable (meaning/micro.py): word centroids learned from tier 1's vectors, so a
                    query can be placed among the notes offline once enough text has been seen
    3. unify        optional and removable (meaning/unify.py): your own chat model writes each note once in one
                    language of your choice and translates a query written in another script

Tiers 1 and 2 give a vector for the query, compared with the vectors tier 1 stored for the notes; tier 3 adds
words to the matching. With no tier available, recall is word matching alone. Vectors are stored per embedder
(`name`), so changing the provider never compares vectors from two different models. This module computes;
Memory writes what it found (glosses) into the notes.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Protocol, Sequence, Union

from .. import providers
from ..providers import Rest, Unavailable
from . import ledger
from .vectors import Vector, cosine, normalize, pack, unpack

log = logging.getLogger("mneme_llm.meaning")

# Similarity below an embedder's floor says nothing. Measured for text-embedding-3-small (256 dimensions) on English
# and Chinese notes: related pairs 0.30-0.60 (mean 0.45), unrelated ones mean 0.18 with 95% under 0.34. Another
# model needs its own measurement: pass `floor=` to its embedder.
FLOOR = 0.33


class Embedder(Protocol):
    name: str    # identifies the model and its settings; vectors from different names are never compared
    floor: float  # the similarity under which two of its vectors are unrelated

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        """One vector per text, in order; raising means this tier is unavailable."""


# ---- tier 1: providers ------------------------------------------------------------------------------
class OpenAIEmbeddings:
    """OpenAI's embeddings API: `text-embedding-3-small` at 256 dimensions costs $0.02 per million tokens and
    places Chinese and English texts about the same thing close together."""

    def __init__(self, api_key: str | None = None, *, model: str = "text-embedding-3-small", dimensions: int = 256,
                 base_url: str = "https://api.openai.com/v1", timeout: float = 15.0, floor: float = FLOOR):
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.model, self.dimensions, self.base_url, self.timeout = model, dimensions, base_url.rstrip("/"), timeout
        self.name, self.floor = f"openai:{model}:{dimensions}", floor
        self.input_tokens = 0

    def _post(self, texts: list[str]) -> dict:
        return providers.post_json(f"{self.base_url}/embeddings", self.api_key,
                                   {"model": self.model, "input": texts, "dimensions": self.dimensions},
                                   timeout=self.timeout, what="embeddings API")

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
    Give it a `name` that changes when the model does, and its own `floor` once you have measured one."""

    def __init__(self, function: EmbedFunction, name: str, *, floor: float = FLOOR):
        self.function, self.name, self.floor = function, name, floor

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        vectors = await providers.call(self.function, list(texts))
        if len(vectors) != len(texts):
            raise Unavailable(f"{self.name} returned {len(vectors)} vectors for {len(texts)} texts")
        return [normalize(vector) for vector in vectors]


# ---- the tiers together -----------------------------------------------------------------------------
class Found:
    """What the tiers made of a query among some notes: how close each note is (`similarities`, by the tier that
    placed the query, with its `floor`), words to add to the matching, and glosses written for the notes."""

    def __init__(self, tier: str = "", *, vector: Vector | None = None, floor: float = 1.0, words: str = "",
                 similarities: dict[int, float] | None = None, glosses: dict[int, str] | None = None):
        self.tier, self.vector, self.floor, self.words = tier, vector, floor, words
        self.similarities, self.glosses = similarities or {}, glosses or {}


class Meaning:
    """The tiers for one store. Each may be None; any that fails passes the query on to the next."""

    BATCH = 64  # notes embedded per request
    TAUGHT_PER_CALL = 256  # stored vectors taught to the centroids per recall (no provider call)

    def __init__(self, store, embedder: Embedder | None = None, micro=None, unify=None):
        self.store, self.embedder, self.micro, self.unify = store, embedder, micro, unify
        self.rest = Rest()  # the embedding provider's
        self.teach_error = ""

    @property
    def name(self) -> str:
        return self.embedder.name if self.embedder is not None else ""

    async def find(self, notes, query: str, *, complete=None) -> Found:
        """What the tiers make of `query` among `notes` (embedding the notes that need it first). `complete`
        gives the unify tier a chat model for this call."""
        await self.prepare_vectors(notes)
        found = await self.query(query, complete=complete)
        if found.vector is not None:
            found.similarities = {id: cosine(found.vector, vector)
                                  for id, vector in self.vectors([note.id for note in notes]).items()}
        elif self.unify is not None and self.unify.ready(complete):  # nothing placed it: glosses help word matching
            found.glosses = await self.unify.glosses(notes, complete=complete)
        return found

    async def query(self, text: str, *, complete=None) -> Found:
        """The best the tiers can do for a query alone (an empty `Found` when none can). Queries teach the
        centroids nothing: they hold words from notes only."""
        if self.embedder is not None and self.rest.up():
            try:
                vector = (await self.embedder.embed([text]))[0]
            except Exception as error:
                self._failed(error)
            else:
                return Found("embeddings", vector=vector, floor=getattr(self.embedder, "floor", FLOOR))
        if self.micro is not None:
            vector = self.micro.vector(text)
            if vector is not None:
                return Found("micro", vector=vector, floor=getattr(self.micro, "floor", FLOOR))
        if self.unify is not None and self.unify.needs_translation(text) and self.unify.ready(complete):
            try:
                return Found("unify", words=await self.unify.translate(text, complete=complete))
            except Exception as error:
                self.unify.rest.failed(error)
        return Found()

    async def prepare_vectors(self, notes) -> int:
        """Embed the notes that have no vector from this embedder yet (in batches); returns how many were added.
        With the centroids on, each new vector teaches them, and so do stored vectors that have not yet."""
        if self.micro is not None and self.name and ledger.untaught(self.store, self.name, 1):
            with self.store.transaction():
                self._teach(ledger.untaught(self.store, self.name, self.TAUGHT_PER_CALL))
        if self.embedder is None or not self.rest.up() or not notes:
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
                self._failed(error)
                break
            # One transaction from here on: a note erased while it was being embedded is left alone (its id may
            # even be another note's by now), and a note another caller embedded meanwhile is not taught twice.
            with self.store.transaction():
                fresh = []
                for note, vector in zip(batch, vectors):
                    if self.store.row("select 1 from memories where id = ? and text = ?", (note.id, note.text)) is None:
                        continue
                    if self.store.execute("insert or ignore into vectors (memory_id, embedder, vector) values "
                                          "(?, ?, ?)", (note.id, self.name, pack(vector))).rowcount:
                        fresh.append((note.id, note.text, vector))
                if self.micro is not None:
                    self._teach(fresh)
            added += len(fresh)
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
        failures = {name: error for name, error in (("embeddings", self.rest.error), ("micro", self.teach_error),
                                                    ("unify", self.unify.rest.error if self.unify else "")) if error}
        report = {"embedder": self.name or None, "failures": failures,
                  "micro": self.micro.report() if self.micro is not None else None,
                  "unify": self.unify.report() if self.unify is not None else None}
        if self.embedder is not None and hasattr(self.embedder, "report"):
            report["embeddings"] = self.embedder.report()
        return report

    def _teach(self, items) -> None:
        """Teach the centroids, in a savepoint: a problem there takes back the lesson, never the vectors."""
        try:
            ledger.teach(self.store, self.name, items)
        except Exception as error:  # the centroids are a bonus: a problem there never fails the tier above
            self.teach_error = f"{type(error).__name__}: {error}"[:200]

    def _failed(self, error: Exception) -> None:
        self.rest.failed(error)
        log.info("embeddings unavailable for %.0f s: %s", self.rest.seconds, self.rest.error)


__all__ = ["Embedder", "Embeddings", "FLOOR", "Found", "Meaning", "OpenAIEmbeddings", "Vector", "cosine", "normalize",
           "pack", "unpack"]
