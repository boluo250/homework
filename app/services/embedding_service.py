from __future__ import annotations

from app.providers.embedding_base import EmbeddingProviderBase


class EmbeddingService:
    def __init__(self, embedding_provider: EmbeddingProviderBase, *, batch_size: int = 32) -> None:
        self.embedding_provider = embedding_provider
        self.batch_size = max(1, batch_size)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            batch = texts[offset : offset + self.batch_size]
            vectors.extend(await self.embedding_provider.embed(batch))
        return vectors
