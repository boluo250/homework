from __future__ import annotations

import re

from app.core.models import AssistantSettings
from app.state.assistant_state import AssistantState


class AssistantIdentityTool:
    def __init__(self, assistant_state: AssistantState) -> None:
        self.assistant_state = assistant_state

    async def get(self, user_id: str) -> AssistantSettings:
        return await self.assistant_state.get_for_user(user_id)

    async def set(self, user_id: str, assistant_name: str) -> AssistantSettings:
        return await self.assistant_state.set_name(user_id, self.suggest(assistant_name))

    def suggest(self, assistant_name: str) -> str:
        cleaned = re.sub(r"\s+", " ", assistant_name).strip(" ，。,:：")
        return cleaned or "TaskMate"
