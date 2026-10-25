"""Meaning tier 1: the embedding providers, which turn text into vectors: OpenAI's, or any function of yours."""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, Protocol, Sequence, Union

from .. import providers
from ..providers import Unavailable
from .vectors import Vector, normalize

# Similarity below an embedder's floor says nothing. Each model's is measured in the file (`calibrate.py`); this is
# the floor until then, or for a model the measurement cannot place: text-embedding-3-small at 256 dimensions,
# measured by hand on English and Chinese notes (related pairs 0.30-0.60, unrelated ones 95% under 0.34).
FLOOR = 0.33


class Embedder(Protocol):
    name: str            # identifies the model and its settings; vectors from different names are never compared
    floor: float | None  # the similarity under which two of its vectors are unrelated (None: measure it)

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        """One vector per text, in order; raising means this tier is unavailable."""


class OpenAIEmbeddings:
    """OpenAI's embeddings API: `text-embedding-3-small` at 256 dimensions costs $0.02 per million tokens and
    places Chinese and English texts about the same thing close together."""

    def __init__(self, api_key: str | None = None, *, model: str = "text-embedding-3-small", dimensions: int = 256,
                 base_url: str = "https://api.openai.com/v1", timeout: float = 15.0, floor: float | None = None):
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
    Give it a `name` that changes when the model does; its floor is measured in the file unless you give one."""

    def __init__(self, function: EmbedFunction, name: str, *, floor: float | None = None):
        self.function, self.name, self.floor = function, name, floor

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        vectors = await providers.call(self.function, list(texts))
        if len(vectors) != len(texts):
            raise Unavailable(f"{self.name} returned {len(vectors)} vectors for {len(texts)} texts")
        return [normalize(vector) for vector in vectors]
