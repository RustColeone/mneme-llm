"""Vectors as the file keeps them (little-endian float32, length 1) and the arithmetic on them."""

from __future__ import annotations

import math
import operator
from array import array
from typing import Sequence

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


def unpack(blob: bytes) -> Vector:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Of two normalized vectors."""
    return sum(map(operator.mul, a, b))
