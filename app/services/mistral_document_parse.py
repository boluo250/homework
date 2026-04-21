from __future__ import annotations

import base64
import json
import re

from app.services.http_client import HttpClient


class MistralDocumentParseService:
    """Parse PDF documents through Mistral OCR."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "mistral-ocr-latest",
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.http_client = HttpClient(timeout_seconds=timeout_seconds)

    async def parse_pdf(self, *, filename: str, content: bytes) -> str:
        if not self.api_key:
            raise ValueError("PDF parsing is not configured. Set MISTRAL_API_KEY to enable OCR.")

        base64_pdf = base64.b64encode(content).decode("utf-8")
        payload = self._build_payload(mime_type="application/pdf", base64_body=base64_pdf)
        response = await self._ocr_request(payload)
        return self._extract_text_from_response(filename=filename, response_status=response.status, body_text=response.body_text)

    async def parse_image(self, *, filename: str, content: bytes) -> str:
        if not self.api_key:
            raise ValueError("Image OCR is not configured. Set MISTRAL_API_KEY to enable OCR.")
        mime_type = _infer_image_mime_type(filename)
        base64_image = base64.b64encode(content).decode("utf-8")
        payload = self._build_payload(mime_type=mime_type, base64_body=base64_image)
        response = await self._ocr_request(payload)
        return self._extract_text_from_response(filename=filename, response_status=response.status, body_text=response.body_text)

    def _build_payload(self, *, mime_type: str, base64_body: str) -> dict:
        return {
            "model": self.model,
            "document": {
                "type": "document_url",
                "document_url": f"data:{mime_type};base64,{base64_body}",
            },
            "include_image_base64": False,
        }

    async def _ocr_request(self, payload: dict):
        response = await self.http_client.request(
            "POST",
            "https://api.mistral.ai/v1/ocr",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json_body=payload,
        )
        return response

    def _extract_text_from_response(self, *, filename: str, response_status: int, body_text: str) -> str:
        body = self._parse_response_json(body_text)
        if response_status >= 400:
            detail = self._extract_error_message(body, fallback=body_text)
            raise ValueError(f"Mistral OCR request failed for {filename}: {detail}")

        pages = body.get("pages", [])
        text_parts = []
        for page in pages:
            markdown = str(page.get("markdown", "")).strip()
            normalized = self._normalize_markdown(markdown)
            if normalized:
                text_parts.append(normalized)

        combined = "\n\n".join(text_parts).strip()
        if not combined:
            raise ValueError(f"Mistral OCR did not extract readable text from {filename}.")
        return combined

    def _parse_response_json(self, body_text: str) -> dict:
        try:
            parsed = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Mistral OCR returned a non-JSON response: {body_text[:240]}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Mistral OCR returned an unexpected response payload.")
        return parsed

    def _extract_error_message(self, body: dict, *, fallback: str) -> str:
        for key in ("message", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = value.get("message")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
        return fallback[:240]

    def _normalize_markdown(self, markdown: str) -> str:
        markdown = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", markdown)
        markdown = markdown.replace("\x00", "").replace("\r", "")
        markdown = re.sub(r"[ \t]{2,}", " ", markdown)
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip()


def _infer_image_mime_type(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"
