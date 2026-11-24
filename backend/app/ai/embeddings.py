"""Text embeddings for semantic search.

HashingEmbedder: dependency-free, deterministic, runs anywhere. It captures word and phrase overlap
(a "lexical-semantic" signal), NOT deep meaning. For real semantic similarity install the optional
`sentence-transformers` package and set EMBEDDER=sentence-transformers (all-MiniLM-L6-v2, 384 dims).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Protocol

from app.core.config import Settings

_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "at",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
        "per",
        "not",
        "no",
    ]  # noqa: E501
)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _tokens(self, text: str) -> list[str]:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]
        return words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token, count in Counter(self._tokens(text)).items():
                h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
                sign = 1.0 if (h >> 63) & 1 else -1.0
                vec[h % self.dim] += sign * (1.0 + math.log(count))
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SentenceTransformerEmbedder:
    name = "sentence-transformers"
    dim = 384

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # optional dependency

        self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.encode(texts, normalize_embeddings=True)]


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "sentence-transformers":
        return SentenceTransformerEmbedder()
    return HashingEmbedder(settings.embedding_dim)


def chunk_text(text: str, max_chars: int = 1500, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks
