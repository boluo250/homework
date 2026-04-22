from __future__ import annotations

from app.providers.llm_base import ChatProviderBase, ToolChatResponse, ToolDefinition


class OpenRouterClient:
    def __init__(self, chat_provider: ChatProviderBase) -> None:
        self.chat_provider = chat_provider

    async def complete(self, *, system_prompt: str, user_message: str) -> str:
        return await self.chat_provider.chat(system_prompt=system_prompt, user_message=user_message)

    async def complete_with_tools(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDefinition],
    ) -> ToolChatResponse:
        return await self.chat_provider.chat_with_tools(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools,
        )
