from __future__ import annotations

from app.services.mistral_document_parse import MistralDocumentParseService
from app.services.openrouter_omni_media_parse import OpenRouterOmniMediaParseService


class CompositeDocumentParseService:
    """PDF 走 Mistral OCR；图片/音频/视频在配置 OpenRouter Omni 时走 MiMo，否则图片可回退 Mistral。"""

    def __init__(
        self,
        *,
        mistral: MistralDocumentParseService | None = None,
        omni: OpenRouterOmniMediaParseService | None = None,
    ) -> None:
        self.mistral = mistral
        self.omni = omni

    async def parse_pdf(self, *, filename: str, content: bytes) -> str:
        if not self.mistral:
            raise ValueError("PDF parsing is not configured. Set MISTRAL_API_KEY.")
        return await self.mistral.parse_pdf(filename=filename, content=content)

    async def parse_image(self, *, filename: str, content: bytes) -> str:
        if self.omni and self.omni.is_configured:
            return await self.omni.parse_image(filename=filename, content=content)
        if self.mistral:
            return await self.mistral.parse_image(filename=filename, content=content)
        raise ValueError(
            "Image extraction is not configured. Set OPENROUTER_API_KEY (MiMo Omni) or MISTRAL_API_KEY (OCR)."
        )

    async def parse_audio(self, *, filename: str, content: bytes) -> str:
        if not self.omni or not self.omni.is_configured:
            raise ValueError(
                "Audio extraction requires OpenRouter MiMo Omni. Set OPENROUTER_API_KEY "
                "(optional: OPENROUTER_OMNI_MODEL, default xiaomi/mimo-v2-omni)."
            )
        return await self.omni.parse_audio(filename=filename, content=content)

    async def parse_video(self, *, filename: str, content: bytes) -> str:
        if not self.omni or not self.omni.is_configured:
            raise ValueError(
                "Video extraction requires OpenRouter MiMo Omni. Set OPENROUTER_API_KEY "
                "(optional: OPENROUTER_OMNI_MODEL, default xiaomi/mimo-v2-omni)."
            )
        return await self.omni.parse_video(filename=filename, content=content)
