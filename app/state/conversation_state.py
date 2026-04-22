from __future__ import annotations

from typing import Any

from app.core.models import Conversation, ConversationMessage, ConversationSummary
from app.services.d1_repo import AppRepository


class ConversationState:
    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    async def create_conversation(self, user_id: str, conversation_id: str | None = None) -> Conversation:
        return await self.repository.get_or_create_conversation(user_id, conversation_id)

    async def get_conversation(self, user_id: str, conversation_id: str | None = None) -> Conversation:
        return await self.repository.get_or_create_conversation(user_id, conversation_id)

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tool_calls_json: str | None = None,
    ) -> ConversationMessage:
        return await self.repository.add_message(
            conversation_id,
            role,
            content,
            tool_calls_json=tool_calls_json,
        )

    async def list_messages(self, conversation_id: str, limit: int = 30) -> list[ConversationMessage]:
        return await self.repository.list_messages(conversation_id, limit=limit)

    async def get_summary(self, conversation_id: str) -> ConversationSummary | None:
        return await self.repository.get_summary(conversation_id)

    async def save_summary(
        self,
        conversation_id: str,
        summary: str,
        source_message_count: int,
    ) -> ConversationSummary:
        return await self.repository.save_summary(conversation_id, summary, source_message_count)

    async def clear_conversation_messages(self, conversation_id: str) -> None:
        if hasattr(self.repository, "messages_by_conversation_id"):
            messages = getattr(self.repository, "messages_by_conversation_id", {})
            messages[conversation_id] = []
            summaries = getattr(self.repository, "summaries_by_conversation_id", {})
            summaries.pop(conversation_id, None)
            return
        if hasattr(self.repository, "_execute"):
            self.repository._execute(  # type: ignore[attr-defined]
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            self.repository._execute(  # type: ignore[attr-defined]
                "DELETE FROM conversation_summaries WHERE conversation_id = ?",
                (conversation_id,),
            )
            return
        if hasattr(self.repository, "_run"):
            await self.repository._run(  # type: ignore[attr-defined]
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            await self.repository._run(  # type: ignore[attr-defined]
                "DELETE FROM conversation_summaries WHERE conversation_id = ?",
                (conversation_id,),
            )


def _row_to_conversation(row: Any) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
