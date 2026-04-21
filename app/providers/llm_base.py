from __future__ import annotations

from abc import ABC, abstractmethod


class ChatProviderBase(ABC):
    @abstractmethod
    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        raise NotImplementedError
