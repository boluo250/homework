from __future__ import annotations

import base64
from pathlib import Path

from app.services.http_client import HttpClient


def _extract_openrouter_message_text(message: object) -> str:
    if message is None:
        return ""
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts = [_extract_openrouter_message_text(item) for item in message]
        return "\n".join(p for p in parts if p).strip()
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]).strip())
        if parts:
            return "\n".join(parts).strip()
    if isinstance(content, str) and content.strip():
        return content.strip()
    for key in ("text", "output_text", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _audio_format_from_suffix(suffix: str) -> str:
    mapping = {
        ".mp3": "mp3",
        ".wav": "wav",
        ".m4a": "m4a",
        ".ogg": "ogg",
        ".flac": "flac",
        ".aac": "aac",
        ".aiff": "aiff",
        ".aif": "aiff",
    }
    return mapping.get(suffix, "mp3")


def _video_mime_from_suffix(suffix: str) -> str:
    mapping = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mpeg": "video/mpeg",
        ".mpg": "video/mpeg",
        ".m4v": "video/x-m4v",
    }
    return mapping.get(suffix, "video/mp4")


def _image_mime_from_suffix(suffix: str) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return mapping.get(suffix, "application/octet-stream")


class OpenRouterOmniMediaParseService:
    """Use OpenRouter multimodal chat (e.g. xiaomi/mimo-v2-omni) to turn media into text for RAG."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "xiaomi/mimo-v2-omni",
        *,
        timeout_seconds: float = 180.0,
        app_name: str = "TaskMate",
        max_tokens: int = 8192,
    ) -> None:
        self.api_key = (api_key or "").strip() or None
        self.model = model
        self.app_name = app_name
        self.max_tokens = max_tokens
        self.http_client = HttpClient(timeout_seconds=timeout_seconds)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _chat_completion(self, *, user_content: list[dict], instruction: str) -> str:
        if not self.api_key:
            raise ValueError("OpenRouter is not configured. Set OPENROUTER_API_KEY for MiMo Omni media extraction.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.app_name:
            headers["X-Title"] = self.app_name

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract structured information from user-uploaded media for a knowledge base. "
                        "Be faithful to the content; transcribe speech and visible text verbatim when possible. "
                        "Use Markdown with clear headings. Primary language: Chinese for explanations; "
                        "keep original language for direct quotes and transcripts."
                    ),
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": instruction}, *user_content],
                },
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
        }
        response = await self.http_client.request(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json_body=payload,
        )
        body = response.json()
        if response.status >= 400:
            detail = response.body_text[:400] if response.body_text else ""
            raise ValueError(f"OpenRouter media extraction failed (HTTP {response.status}): {detail}")

        choices = body.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter returned no choices for media extraction.")
        message = choices[0].get("message", {})
        text = _extract_openrouter_message_text(message)
        if not text:
            raise ValueError("OpenRouter returned empty text for media extraction.")
        return text.strip()

    async def parse_image(self, *, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        mime = _image_mime_from_suffix(suffix)
        b64 = base64.b64encode(content).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        instruction = (
            "请完成：1) OCR：逐段转写图中所有可读文字；2) 简要说明图表、截图或场景中的关键非文字信息。"
            f"文件名：{filename}"
        )
        return await self._chat_completion(
            instruction=instruction,
            user_content=[{"type": "image_url", "image_url": {"url": data_url}}],
        )

    async def parse_audio(self, *, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        audio_format = _audio_format_from_suffix(suffix)
        b64 = base64.b64encode(content).decode("ascii")
        instruction = (
            "请对音频做完整听写（ASR）：按时间顺序输出可识别的语音内容；若有明显背景声或音乐可简短标注。"
            f"文件名：{filename}"
        )
        return await self._chat_completion(
            instruction=instruction,
            user_content=[
                {
                    "type": "input_audio",
                    "input_audio": {"data": b64, "format": audio_format},
                }
            ],
        )

    async def parse_video(self, *, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        mime = _video_mime_from_suffix(suffix)
        b64 = base64.b64encode(content).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        instruction = (
            "请分析该视频：1) 语音听写（能听清的部分）；2) 关键画面与动作的时间线描述；3) 画面中出现的可读文字（若有）。"
            f"文件名：{filename}"
        )
        return await self._chat_completion(
            instruction=instruction,
            user_content=[{"type": "video_url", "video_url": {"url": data_url}}],
        )
