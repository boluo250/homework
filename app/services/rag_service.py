from __future__ import annotations

from app.providers.embedding_base import EmbeddingProviderBase
from app.services.qdrant_store import QdrantStore

# 与 FileParser / 上传解析后的 payload source_type（扩展名去掉点）保持一致，供向量检索过滤
RAG_SOURCE_TYPES = [
    "txt",
    "md",
    "pdf",
    "docx",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "mp3",
    "wav",
    "m4a",
    "ogg",
    "flac",
    "aac",
    "aiff",
    "aif",
    "mp4",
    "mov",
    "webm",
    "mpeg",
    "mpg",
    "m4v",
]


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
        filters = {"user_id": user_id, "source_type": RAG_SOURCE_TYPES}
        if file_ids:
            filters["file_id"] = file_ids
        matches = await self.qdrant_store.search(query_vector=vectors[0], filters=filters, limit=limit)
        return [{"text": match.text, "score": match.score, "payload": match.payload} for match in matches]
