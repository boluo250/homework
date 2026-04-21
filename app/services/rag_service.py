from __future__ import annotations

from app.providers.embedding_base import EmbeddingProviderBase
from app.services.qdrant_store import QdrantStore


class RagService:
    def __init__(
        self,
        embedding_provider: EmbeddingProviderBase,
        qdrant_store: QdrantStore,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.qdrant_store = qdrant_store

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        file_ids: list[str] | None = None,
        limit: int = 4,
    ) -> list[dict]:
        vectors = await self.embedding_provider.embed([query])
        filters = {"user_id": user_id, "source_type": ["txt", "md", "pdf", "docx"]}
        if file_ids:
            filters["file_id"] = file_ids
        matches = await self.qdrant_store.search(query_vector=vectors[0], filters=filters, limit=limit)
        return [{"text": match.text, "score": match.score, "payload": match.payload} for match in matches]
