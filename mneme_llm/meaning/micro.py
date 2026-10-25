"""Tier 2 of meaning (optional, removable): word centroids learned from the embedding provider's vectors.

Every note the provider embeds teaches each of its search terms the note's vector; a term keeps the running mean
of the vectors of the notes it appeared in (the account is kept by `meaning/ledger.py`, so a note that is erased
takes back exactly what it taught, with or without this file). A query is placed at the weighted mean of its
terms' centroids, with rarer terms counting more. Because the provider's space puts "猫" and "cat" close
together, the centroids carry that over, so a Chinese query can still find an English note when the provider
cannot be reached.

It answers only after `min_texts` notes were learned, and only for a query whose known terms carry at least
`min_coverage` of its weight; otherwise it abstains and the next tier is asked. Delete this file (or pass
`meaning_micro=False`) and nothing else changes.
"""

from __future__ import annotations

import math

from .. import text as texts
from . import ledger
from .vectors import normalize, unpack

# Centroids are averages, so they sit closer together than real embeddings: the floor of similarity is higher.
FLOOR = 0.45


class TermCentroids:
    name = "micro"

    def __init__(self, store, embedder: str, *, min_texts: int = 40, min_coverage: float = 0.6, floor: float = FLOOR):
        self.store, self.embedder = store, embedder
        self.min_texts, self.min_coverage, self.floor = min_texts, min_coverage, floor

    @property
    def learned(self) -> int:
        return ledger.learned(self.store, self.embedder)

    def vector(self, text: str) -> list | None:
        """Where `text` sits among the notes, or None when too little of it is known."""
        learned = self.learned
        terms = texts.terms(text)
        if learned < self.min_texts or not terms or not ledger.current(self.store, self.embedder):
            return None
        rows = {}
        for start in range(0, len(terms), 400):
            chunk = terms[start:start + 400]
            found = self.store.rows(f"select term, count, vector from meaning_terms where embedder = ? and term in "
                                    f"({', '.join('?' * len(chunk))})", (self.embedder, *chunk))
            rows.update({row["term"]: row for row in found})
        unknown_weight = math.log(1 + learned)
        total = known = 0.0
        mixed: list[float] | None = None
        for term in terms:
            row = rows.get(term)
            weight = math.log(1 + learned / row["count"]) if row is not None else unknown_weight
            total += weight
            if row is None:
                continue
            known += weight
            centroid = unpack(row["vector"])
            mixed = [weight * value for value in centroid] if mixed is None else \
                [old + weight * value for old, value in zip(mixed, centroid)]
        if mixed is None or known / total < self.min_coverage:
            return None
        return normalize(mixed)

    def report(self) -> dict:
        row = self.store.row("select count(*) as n from meaning_terms where embedder = ?", (self.embedder,))
        return {"texts": self.learned, "terms": row["n"], "answers": self.learned >= self.min_texts}
