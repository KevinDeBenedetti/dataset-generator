"""A deterministic stand-in for the local embedding model.

Bag of words hashed into a small vector: texts sharing words score high,
unrelated ones near zero — enough to exercise the semantic code paths without
downloading a model.
"""

import hashlib
import re
from typing import List, Sequence

import numpy as np

from server.services.semantic import normalize

DIM = 256


def _bucket(word: str) -> int:
    return int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM


class FakeEmbedder:
    model_name = "fake/bag-of-words"

    def __init__(self) -> None:
        self.calls: List[List[str]] = []

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls.append(list(texts))
        matrix = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                matrix[row, _bucket(word)] += 1.0
        return normalize(matrix)
