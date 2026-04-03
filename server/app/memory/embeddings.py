"""Embedding interfaces for memory-pipeline integration."""

from __future__ import annotations

from hashlib import blake2b
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Minimal interface for embedding memory text."""

    def embed_text(self, text: str) -> list[float] | None:
        """Return an embedding vector or ``None`` when embeddings are disabled."""


class NullEmbeddingProvider:
    """Honest default provider used until a real embedding backend is configured."""

    def embed_text(self, text: str) -> list[float] | None:
        """Disable embedding generation cleanly."""

        return None


class DeterministicHashEmbeddingProvider:
    """Cheap deterministic embedding stub for tests and local pipeline verification."""

    dimension = 1536

    def embed_text(self, text: str) -> list[float] | None:
        """Project text into a stable fixed-width numeric vector."""

        vector = [0.0] * self.dimension
        for index in range(32):
            digest = blake2b(f"{text}:{index}".encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:2], "big") % self.dimension
            magnitude = (int.from_bytes(digest[2:4], "big") / 65535.0) * 2.0 - 1.0
            vector[bucket] += magnitude / 8.0
        return vector
