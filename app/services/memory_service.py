from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from app.providers.embedding_base import EmbeddingProviderBase
from app.services.qdrant_store import QdrantStore


class MemoryService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProviderBase,
        qdrant_store: QdrantStore,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.qdrant_store = qdrant_store

    async def store_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str,
        role: str,
        content: str,
    ) -> None:
        text = content.strip()
        if not text:
            return
        vector = (await self.embedding_provider.embed([text]))[0]
        await self.qdrant_store.create_payload_index("user_id")
        await self.qdrant_store.create_payload_index("source_type")
        await self.qdrant_store.create_payload_index("conversation_id")
        point = {
            "id": str(uuid5(NAMESPACE_URL, f"memory:{message_id}")),
            "vector": vector,
            "payload": {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "role": role,
                "source_type": "chat_memory",
                "text": text,
            },
        }
        await self.qdrant_store.upsert_chunks([point])

    async def retrieve_memories(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 4,
    ) -> list[dict]:
        text = query.strip()
        if not text:
            return []
        vector = (await self.embedding_provider.embed([text]))[0]
        matches = await self.qdrant_store.search(
            query_vector=vector,
            filters={"user_id": user_id, "source_type": "chat_memory"},
            limit=limit,
        )
        return [{"text": match.text, "score": match.score, "payload": match.payload} for match in matches]
