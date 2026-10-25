"""Tier 2 of meaning (optional, removable): word centroids learned from the embedding provider's vectors.

Every text the provider embeds (notes, and queries) teaches each of its search terms the text's vector; a term
keeps the running mean of the vectors of the texts it appeared in. A query is then placed at the weighted mean
of its terms' centroids, with rarer terms counting more. Because the provider's space puts "猫" and "cat"
close together, the centroids carry that over, so a Chinese query can still find an English note when the
provider cannot be reached.

It answers only after `min_texts` texts were learned, and only for a query whose known terms carry at least
`min_coverage` of its weight; otherwise it abstains and the next tier is asked. Delete this file (or pass
`meaning_micro=False`) and nothing else changes; its rows live in the `meaning_terms` table.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from .. import text as texts
from . import normalize, pack, unpack


class TermCentroids:
    name = "micro"

    def __init__(self, store, embedder: str, *, min_texts: int = 40, min_coverage: float = 0.6):
        self.store, self.embedder = store, embedder
        self.min_texts, self.min_coverage = min_texts, min_coverage

    @property
    def learned(self) -> int:
        return int(self.store.meta(f"meaning_texts:{self.embedder}") or 0)

    def learn(self, pairs: Iterable[tuple[str, Sequence[float]]]) -> None:
        """Teach each text's terms its vector (running means, so the table stays one row per term)."""
        pairs = [(text, vector) for text, vector in pairs if text.strip()]
        if not pairs:
            return
        with self.store.transaction():
            for text, vector in pairs:
                for term in texts.terms(text):
                    row = self.store.row("select count, vector from meaning_terms where embedder = ? and term = ?",
                                         (self.embedder, term))
                    if row is None:
                        count, mean = 1, list(vector)
                    else:
                        count = row["count"] + 1
                        mean = [old + (new - old) / count for old, new in zip(unpack(row["vector"]), vector)]
                    self.store.execute("insert or replace into meaning_terms (embedder, term, count, vector) values "
                                       "(?, ?, ?, ?)", (self.embedder, term, count, pack(mean)))
            self.store.set_meta(f"meaning_texts:{self.embedder}", str(self.learned + len(pairs)))

    def vector(self, text: str) -> list | None:
        """Where `text` sits among the notes, or None when too little of it is known."""
        learned = self.learned
        terms = texts.terms(text)
        if learned < self.min_texts or not terms:
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

    def reset(self) -> None:
        with self.store.transaction():
            self.store.execute("delete from meaning_terms where embedder = ?", (self.embedder,))
            self.store.execute("delete from meta where key = ?", (f"meaning_texts:{self.embedder}",))
