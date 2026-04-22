from __future__ import annotations

from app.core.models import AssistantSettings
from app.services.d1_repo import AppRepository


class AssistantState:
    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    async def get_for_user(self, user_id: str) -> AssistantSettings:
        return await self.repository.get_or_create_assistant_settings(user_id)

    async def set_name(self, user_id: str, bot_name: str) -> AssistantSettings:
        return await self.repository.update_assistant_name(user_id, bot_name)

    async def reset(self, user_id: str) -> AssistantSettings:
        return await self.repository.update_assistant_name(user_id, "TaskMate")
