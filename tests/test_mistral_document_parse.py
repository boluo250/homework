import asyncio
import json

from app.services.http_client import HttpResponseData
from app.services.mistral_document_parse import MistralDocumentParseService


def test_mistral_parser_collects_markdown_pages() -> None:
    async def run() -> None:
        service = MistralDocumentParseService(api_key="test-key")

        async def fake_request(method, url, *, headers=None, json_body=None):
            assert method == "POST"
            assert url == "https://api.mistral.ai/v1/ocr"
            assert headers["Authorization"] == "Bearer test-key"
            assert json_body["model"] == "mistral-ocr-latest"
            return HttpResponseData(
                status=200,
                body_text=json.dumps(
                    {
                        "pages": [
                            {"markdown": "# 简历\n姓名：小李"},
                            {"markdown": "经历：Cloudflare Worker 项目"},
                        ]
                    }
                ),
            )

        service.http_client.request = fake_request
        text = await service.parse_pdf(filename="resume.pdf", content=b"%PDF-test")
        assert "姓名：小李" in text
        assert "Cloudflare Worker" in text

    asyncio.run(run())


def test_mistral_parser_requires_api_key() -> None:
    async def run() -> None:
        service = MistralDocumentParseService()
        try:
            await service.parse_pdf(filename="resume.pdf", content=b"%PDF-test")
        except ValueError as exc:
            assert "MISTRAL_API_KEY" in str(exc)
        else:
            raise AssertionError("Expected parse_pdf to fail without credentials")

    asyncio.run(run())


def test_mistral_image_parser_uses_image_mime_type() -> None:
    async def run() -> None:
        service = MistralDocumentParseService(api_key="test-key")

        async def fake_request(method, url, *, headers=None, json_body=None):
            assert method == "POST"
            assert "data:image/png;base64," in json_body["document"]["document_url"]
            return HttpResponseData(
                status=200,
                body_text=json.dumps({"pages": [{"markdown": "图片识别文字"}]}),
            )

        service.http_client.request = fake_request
        text = await service.parse_image(filename="note.png", content=b"img")
        assert "图片识别文字" in text

    asyncio.run(run())
