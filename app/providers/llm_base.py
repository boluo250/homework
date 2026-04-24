from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatProviderBase(ABC):
    @abstractmethod
    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        raise NotImplementedError

    def supports_tool_calls(self) -> bool:
        return False

    async def chat_with_tools(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDefinition],
    ) -> ToolChatResponse:
        return ToolChatResponse(content=await self.chat(system_prompt=system_prompt, user_message=user_message))

    async def chat_stream(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> AsyncIterator[str]:
        reply = await self.chat(system_prompt=system_prompt, user_message=user_message)
        if reply:
            yield reply
