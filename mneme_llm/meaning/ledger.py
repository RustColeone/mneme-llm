"""The account of what notes taught the word centroids (meaning tier 2), so that removing a note takes back exactly
what it taught (docs/FORMAT.md, "meaning_terms"):

    vectors.taught            the terms each note's vector taught, space-separated (null: it taught nothing)
    meaning_terms             each term's count and the running mean of the vectors that taught it
    meta meaning_texts:<e>    how many notes embedder <e> taught: always its vectors whose `taught` is not null
    meta meaning_version:<e>  the tokenizer that split their terms

This is not part of the removable tier. The tier only reads the centroids; whoever deletes notes keeps this
account (`unteach`), with the tier installed or not, or a deleted note's words would stay in the file.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .. import text as texts
from .vectors import pack, unpack

TEXTS = "meaning_texts:{}"
VERSION = "meaning_version:{}"


def learned(store, embedder: str) -> int:
    return int(store.meta(TEXTS.format(embedder)) or 0)


def current(store, embedder: str) -> bool:
    """Whether the centroids were split by this tokenizer (terms split another way would not match)."""
    return store.meta(VERSION.format(embedder)) in (None, texts.version())


def teach(store, embedder: str, items: Iterable[tuple[int, str, Sequence[float]]]) -> None:
    """Teach each `(memory_id, text, vector)` note's terms its vector and record what it taught, in one transaction
    (a savepoint of the caller's). The vector rows must exist; centroids from another tokenizer start over."""
    items = list(items)
    if not items:
        return
    with store.transaction():
        if not current(store, embedder):
            reset(store, embedder)
        store.set_meta(VERSION.format(embedder), texts.version())
        for memory_id, text, vector in items:
            terms = texts.terms(text)
            for term in terms:
                row = store.row("select count, vector from meaning_terms where embedder = ? and term = ?",
                                (embedder, term))
                if row is None:
                    count, mean = 1, list(vector)
                else:
                    count = row["count"] + 1
                    mean = [old + (new - old) / count for old, new in zip(unpack(row["vector"]), vector)]
                store.execute("insert or replace into meaning_terms (embedder, term, count, vector) values "
                              "(?, ?, ?, ?)", (embedder, term, count, pack(mean)))
            store.execute("update vectors set taught = ? where memory_id = ? and embedder = ?",
                          (" ".join(terms), memory_id, embedder))
        store.set_meta(TEXTS.format(embedder), str(learned(store, embedder) + len(items)))


def unteach(store, ids: Sequence[int]) -> None:
    """Before notes are deleted (or an id is reused): take back what their vectors taught and drop the vectors.
    Each taught term loses the vector from its running mean, and a term only they had is gone. No tokenizer is
    needed, and the cost follows the notes, not the file."""
    rows = []
    with store.transaction():
        for start in range(0, len(ids), 500):
            chunk = list(ids[start:start + 500])
            marks = ", ".join("?" * len(chunk))
            rows += store.rows(f"select embedder, vector, taught from vectors where taught is not null and "
                               f"memory_id in ({marks})", chunk)
            store.execute(f"delete from vectors where memory_id in ({marks})", chunk)
        for embedder in {row["embedder"] for row in rows}:
            mine = [row for row in rows if row["embedder"] == embedder]
            for row in mine:
                vector = unpack(row["vector"])
                for term in row["taught"].split():
                    found = store.row("select count, vector from meaning_terms where embedder = ? and term = ?",
                                      (embedder, term))
                    if found is None:
                        continue
                    if found["count"] <= 1:
                        store.execute("delete from meaning_terms where embedder = ? and term = ?", (embedder, term))
                        continue
                    count = found["count"] - 1
                    mean = [(old * found["count"] - value) / count
                            for old, value in zip(unpack(found["vector"]), vector)]
                    store.execute("update meaning_terms set count = ?, vector = ? where embedder = ? and term = ?",
                                  (count, pack(mean), embedder, term))
            store.set_meta(TEXTS.format(embedder), str(max(0, learned(store, embedder) - len(mine))))


def reset(store, embedder: str) -> None:
    """Forget every lesson of `embedder`; its stored vectors are taught again from the file (`untaught`)."""
    with store.transaction():
        store.execute("delete from meaning_terms where embedder = ?", (embedder,))
        store.execute("delete from meta where key in (?, ?)", (TEXTS.format(embedder), VERSION.format(embedder)))
        store.execute("update vectors set taught = null where embedder = ?", (embedder,))


def untaught(store, embedder: str, limit: int) -> list[tuple[int, str, list]]:
    """Notes whose vectors are stored but have taught nothing yet (after a reset, or in a file from an earlier
    build), as `teach` takes them."""
    rows = store.rows("select v.memory_id, v.vector, m.text from vectors v join memories m on m.id = v.memory_id "
                      "where v.embedder = ? and v.taught is null limit ?", (embedder, limit))
    return [(row["memory_id"], row["text"], unpack(row["vector"])) for row in rows]


def repair(store) -> list[str]:
    """Reset the centroids of every embedder whose account does not add up: changed by something that keeps
    none (a build from before `vectors.taught`, maybe still running). Returns the embedders reset."""
    broken = []
    with store.transaction():  # the count and the account read together, so another writer can't come between
        embedders = {row["embedder"] for row in store.rows("select distinct embedder from meaning_terms")}
        embedders |= {row["key"].split(":", 1)[1] for row in store.rows("select key from meta where key like ?",
                                                                        (TEXTS.format("%"),))}
        for embedder in sorted(embedders):
            taught = store.row("select count(*) as n from vectors where embedder = ? and taught is not null",
                               (embedder,))["n"]
            if taught != learned(store, embedder) or not taught:
                reset(store, embedder)
                broken.append(embedder)
    return broken
