"""Meaning: finding notes by what they mean, not only by the words they share, in three tiers that fall through.

    1. embeddings   a provider turns text into vectors: `OpenAIEmbeddings()` (text-embedding-3-small at 256
                    dimensions, with OPENAI_API_KEY), or any function you give (`Embeddings(fn, name=...)`)
    2. micro        optional and removable (meaning/micro.py): word centroids learned from tier 1's vectors, so a
                    query can be placed among the notes offline once enough text has been seen
    3. unify        optional and removable (meaning/unify.py): your own chat model writes each note once in one
                    language of your choice and translates a query written in another script

Tiers 1 and 2 give a vector for the query, compared with the vectors tier 1 stored for the notes; tier 3 adds
words to the matching. With no tier available, recall is word matching alone. Vectors are stored per embedder
(`name`), so changing the provider never compares vectors from two different models, and each model's floor (the
similarity under which a note says nothing) is measured in the file. The providers are in `embedders.py`, the
measuring in `calibrate.py`; this module has the tiers work together. It computes; Memory writes what it found
(glosses) into the notes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from ..providers import Rest, Unavailable
from . import calibrate, ledger
from .embedders import FLOOR, Embedder, Embeddings, OpenAIEmbeddings
from .vectors import Vector, cosine, normalize, pack, unpack, usable

log = logging.getLogger("mneme_llm.meaning")

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
        self._measuring = False

    @property
    def floor(self) -> float:
        """The embedder's floor: its own when it was given one, else the one measured in this file, else FLOOR."""
        fixed = getattr(self.embedder, "floor", None)
        if fixed is not None:
            return fixed
        record = calibrate.read(self.store, self.name) if self.name else None
        return record["floor"] if record else FLOOR

    @property
    def set_floor(self) -> float:
        """The floor as the bundled set placed it, a message against a note, before the file's own notes moved it:
        notes about the same people resemble each other, and a message does not resemble them more for that. What
        a look's bar stands on (`episodes.py`)."""
        fixed = getattr(self.embedder, "floor", None)
        if fixed is not None:
            return fixed
        record = calibrate.read(self.store, self.name) if self.name else None
        measured = record.get("set") if record else None
        return measured["floor"] if isinstance(measured, dict) and "floor" in measured else self.floor

    @property
    def name(self) -> str:
        return self.embedder.name if self.embedder is not None else ""

    async def find(self, notes, query: str, *, complete=None) -> Found:
        """What the tiers make of `query` among `notes` (embedding the notes that need it first). `complete`
        gives the unify tier a chat model for this call."""
        await self.prepare_vectors(notes)
        found = await self.query(query, complete=complete)
        if found.vector is not None:  # (a vector of another length is from another model under the same name)
            found.similarities = {id: cosine(found.vector, vector)
                                  for id, vector in self.vectors([note.id for note in notes]).items()
                                  if len(vector) == len(found.vector)}
        elif self.unify is not None and self.unify.ready(complete):  # nothing placed it: glosses help word matching
            found.glosses = await self.unify.glosses(notes, complete=complete)
        return found

    async def query(self, text: str, *, complete=None) -> Found:
        """The best the tiers can do for a query alone (an empty `Found` when none can). Queries teach the
        centroids nothing: they hold words from notes only."""
        if self.embedder is not None and self.rest.up():
            try:
                vector = usable((await self.embedder.embed([text]))[0])
                if vector is None:
                    raise Unavailable(f"{self.name} gave the query a vector that is not finite")
            except Exception as error:
                self._failed(error)
            else:
                return Found("embeddings", vector=vector, floor=self.floor)
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

    async def embed(self, texts: Sequence[str]) -> list[Vector | None] | None:
        """Tier 1's vectors for some texts (normalized; None for one that is not finite), or None when the embedder
        is not there or not answering (the failure is recorded as any other)."""
        if self.embedder is None or not self.rest.up() or not texts:
            return None
        try:
            vectors = await self.embedder.embed(list(texts))
            if len(vectors) != len(texts):
                raise Unavailable(f"{self.name} returned {len(vectors)} vectors for {len(texts)} texts")
        except Exception as error:
            self._failed(error)
            return None
        return [usable(vector) for vector in vectors]

    async def prepare_vectors(self, notes) -> int:
        """Embed the notes that have no vector from this embedder yet (in batches); returns how many were added.
        With the centroids on, each new vector teaches them, and so do stored vectors that have not yet. Then the
        embedder's floor is measured, the first time, and refined as the file grows."""
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
                if len(vectors) != len(batch):
                    raise Unavailable(f"{self.name} returned {len(vectors)} vectors for {len(batch)} texts")
            except Exception as error:
                self._failed(error)
                break
            # One transaction from here on: a note erased while it was being embedded is left alone (its id may
            # even be another note's by now), and a note another caller embedded meanwhile is not taught twice.
            with self.store.transaction():
                fresh = []
                for note, vector in zip(batch, vectors):
                    vector = usable(vector)  # normalized; a vector that is not finite is not kept
                    if vector is None or self.store.row("select 1 from memories where id = ? and text = ?",
                                                        (note.id, note.text)) is None:
                        continue
                    if self.store.execute("insert or ignore into vectors (memory_id, embedder, vector) values "
                                          "(?, ?, ?)", (note.id, self.name, pack(vector))).rowcount:
                        fresh.append((note.id, note.text, vector))
                if self.micro is not None:
                    self._teach(fresh)
            added += len(fresh)
        await self._measure()
        return added

    async def _measure(self) -> None:
        """The floor of an embedder given none: measured on the bundled set once (one request), then refined by the
        file's own notes each time their number doubles (no request)."""
        if getattr(self.embedder, "floor", None) is not None or self._measuring or not self.rest.up():
            return
        self._measuring = True  # one measurement at a time; a recall meanwhile uses the floor there is
        try:
            record = calibrate.read(self.store, self.name)
            if record is None:
                try:
                    record = await calibrate.measure(self.embedder, FLOOR)
                except Exception as error:
                    self._failed(error)
                    return
                calibrate.write(self.store, self.name, record)
            if calibrate.due(self.store, record):  # (thousands of products: off the event loop)
                record = await asyncio.to_thread(calibrate.refine, self.store, self.name, record)
                calibrate.write(self.store, self.name, record)
        finally:
            self._measuring = False

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
        report = {"embedder": self.name or None, "floor": self._floor_report(), "failures": failures,
                  "micro": self.micro.report() if self.micro is not None else None,
                  "unify": self.unify.report() if self.unify is not None else None}
        if self.embedder is not None and hasattr(self.embedder, "report"):
            report["embeddings"] = self.embedder.report()
        return report

    def _floor_report(self) -> dict | None:
        if self.embedder is None:
            return None
        if getattr(self.embedder, "floor", None) is not None:
            return {"value": self.embedder.floor, "by": "given"}
        record = calibrate.read(self.store, self.name)
        if record is None:
            return {"value": FLOOR, "by": "default (not measured yet)"}
        by = "file" if (record.get("file") or {}).get("shift") is not None else "set" if record["separated"] else \
            "default (the set did not separate)"
        return {"value": record["floor"], "by": by, "set": record["set"], "file": record.get("file")}

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
