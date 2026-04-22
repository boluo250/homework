from __future__ import annotations

import json

from app.services.http_client import HttpClient

from .llm_base import ChatProviderBase, ToolCall, ToolChatResponse, ToolDefinition


class OpenRouterChatProvider(ChatProviderBase):
    """OpenRouter chat provider with a graceful local fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "openrouter/auto",
        timeout_seconds: float = 20.0,
        app_name: str = "TaskMate",
        max_tokens: int = 4000,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.app_name = app_name
        self.max_tokens = max_tokens
        self.http_client = HttpClient(timeout_seconds=timeout_seconds)

    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        response = await self._request_openrouter(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=None,
        )
        return response.content or "OpenRouter returned an empty response."

    def supports_tool_calls(self) -> bool:
        return bool(self.api_key)

    async def chat_with_tools(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDefinition],
    ) -> ToolChatResponse:
        return await self._request_openrouter(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools,
        )

    async def _request_openrouter(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDefinition] | None,
    ) -> ToolChatResponse:
        if not self.api_key:
            return ToolChatResponse(
                content=(
                    "OpenRouter provider is not configured yet, so I am using the local fallback "
                    "response path. You can keep chatting, and task features still work."
                )
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.app_name:
            headers["X-Title"] = self.app_name

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        try:
            response = await self.http_client.request(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json_body=payload,
            )
            body = response.json()
            if response.status >= 400:
                return ToolChatResponse(content=f"OpenRouter request failed with HTTP {response.status}: {response.body_text[:300]}")
        except Exception as exc:  # noqa: BLE001
            return ToolChatResponse(content=f"OpenRouter request failed: {exc}")

        choices = body.get("choices", [])
        if not choices:
            return ToolChatResponse(content="OpenRouter returned no choices.")
        message = choices[0].get("message", {})
        tool_calls = self._extract_tool_calls(message)
        if tool_calls:
            return ToolChatResponse(
                content=self._extract_text(message) or None,
                tool_calls=tool_calls,
            )
        text = self._extract_text(message)
        if text:
            return ToolChatResponse(content=self._finalize_text(text, choices[0]))
        choice_text = self._extract_text(choices[0])
        if choice_text:
            return ToolChatResponse(content=self._finalize_text(choice_text, choices[0]))
        return ToolChatResponse(content="OpenRouter returned an empty response.")

    def _extract_text(self, payload: object) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, list):
            parts = [self._extract_text(item) for item in payload]
            return "\n".join(part for part in parts if part).strip()
        if not isinstance(payload, dict):
            return ""

        content = payload.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text"):
                        parts.append(str(item.get("text")).strip())
                    elif item.get("content"):
                        nested = self._extract_text(item.get("content"))
                        if nested:
                            parts.append(nested)
                elif isinstance(item, str) and item.strip():
                    parts.append(item.strip())
            if parts:
                return "\n".join(parts).strip()
        elif isinstance(content, str) and content.strip():
            return content.strip()

        # Some providers place the actual answer in alternative fields when content is null.
        for key in ("text", "output_text", "reasoning", "refusal"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                nested = self._extract_text(value)
                if nested:
                    return nested

        if isinstance(content, dict):
            nested = self._extract_text(content)
            if nested:
                return nested

        return ""

    def _finalize_text(self, text: str, choice: dict) -> str:
        finish_reason = str(choice.get("finish_reason", "") or "").strip().lower()
        if finish_reason == "length":
            return text.rstrip() + "\n\n[回答因输出长度限制被截断]"
        return text.strip()

    def _extract_tool_calls(self, payload: object) -> list[ToolCall]:
        if not isinstance(payload, dict):
            return []
        raw_calls = payload.get("tool_calls")
        if not isinstance(raw_calls, list):
            return []
        tool_calls: list[ToolCall] = []
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name", "")).strip()
            if not name:
                continue
            raw_args = function.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
            except Exception:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(ToolCall(name=name, arguments=arguments))
        return tool_calls
