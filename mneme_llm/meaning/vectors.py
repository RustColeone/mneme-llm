"""Vectors as the file keeps them (little-endian float32, length 1) and the arithmetic on them."""

from __future__ import annotations

import heapq
import math
import operator
from array import array
from typing import Iterable, Sequence

try:  # optional: compares thousands of vectors at once
    import numpy
except ImportError:  # (the library needs nothing but Python)
    numpy = None

Vector = list


def normalize(vector: Sequence[float]) -> Vector:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def usable(vector) -> Vector | None:
    """A vector as it can be stored and compared (normalized), or None for one with a value that is not a finite
    number, or with no length at all."""
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError):
        return None
    if not values or not all(math.isfinite(value) for value in values) or not any(values):
        return None
    return normalize(values)


def pack(vector: Sequence[float]) -> bytes:
    return array("f", vector).tobytes()


def raw(blob: bytes) -> array:
    """A kept vector as it is, for reading many at once."""
    values = array("f")
    values.frombytes(blob)
    return values


def unpack(blob: bytes) -> Vector:
    return list(raw(blob))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Of two normalized vectors."""
    return sum(map(operator.mul, a, b))


def drop(store, ids: Iterable[int]) -> None:
    """The vectors of these notes gone, whatever embedder made them: a vector is the note's words in another form."""
    store.rows_in("delete from vectors where memory_id in ({})", ids)


class Matrix:
    """Many vectors of one length, compared with one at a time; with numpy, at once. A row of another length is counted
    and left out, as it can only be from another model."""

    def __init__(self):
        self.ids: list[int] = []
        self.ats: list[float] = []
        self.read = 0   # rows added, a vector of another length among them (it is not compared)
        self.last = 0   # the highest id added
        self._data = None
        self.count = 0

    def add(self, id: int, vector, at: float = 0.0) -> None:
        self.read += 1
        self.last = max(self.last, id)
        if numpy is not None:
            if self._data is None:
                self._data = numpy.zeros((64, len(vector)), dtype=numpy.float32)
            elif len(vector) != self._data.shape[1]:
                return
            if self.count == len(self._data):
                self._data = numpy.concatenate([self._data, numpy.zeros_like(self._data)])
            self._data[self.count] = vector
        else:
            if self._data is None:
                self._data = []
            elif len(vector) != len(self._data[0]):
                return
            self._data.append(list(vector))
        self.ids.append(id)
        self.ats.append(at)
        self.count += 1

    def similarities(self, vector):
        """Cosine with each vector, in the order of `ids` (an array with numpy, else a list; empty when there are
        none of this length)."""
        if not self.count:
            return []
        if numpy is not None:
            if len(vector) != self._data.shape[1]:
                return []
            return self._data[:self.count] @ numpy.asarray(vector, dtype=numpy.float32)
        if len(vector) != len(self._data[0]):
            return []
        return [cosine(row, vector) for row in self._data]

    def order(self, similarities) -> list[int]:
        """Positions in `ids`, the closest first."""
        if numpy is not None and len(similarities):
            return numpy.argsort(-similarities, kind="stable").tolist()
        return sorted(range(len(similarities)), key=lambda index: -similarities[index])

    def nearest(self, similarities, before: float, line: float, count: int) -> list[int]:
        """The ids of the `count` closest with an `at` before `before`, those at least `line` close."""
        if not len(similarities):
            return []
        if numpy is not None:
            values = numpy.where(numpy.asarray(self.ats) < before, similarities, -numpy.inf)
            top = numpy.argpartition(-values, count)[:count] if len(values) > count else range(len(values))
            top = sorted(top, key=lambda index: -values[index])
            return [self.ids[index] for index in top if values[index] >= line]
        earlier = heapq.nlargest(count, ((value, id) for id, at, value in zip(self.ids, self.ats, similarities)
                                         if at < before))
        return [id for value, id in earlier if value >= line]
