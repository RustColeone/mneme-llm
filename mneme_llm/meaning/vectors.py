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


def pack(vector: Sequence[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> Vector:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Of two normalized vectors."""
    return sum(map(operator.mul, a, b))
