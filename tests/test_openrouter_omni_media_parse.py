import asyncio
import json

from app.services.http_client import HttpResponseData
from app.services.openrouter_omni_media_parse import OpenRouterOmniMediaParseService


def test_omni_parse_image_posts_multimodal_payload() -> None:
    async def run() -> None:
        service = OpenRouterOmniMediaParseService(api_key="test-key", model="xiaomi/mimo-v2-omni")

        async def fake_request(method, url, *, headers=None, json_body=None):
            assert method == "POST"
            assert "openrouter.ai/api/v1/chat/completions" in url
            assert json_body["model"] == "xiaomi/mimo-v2-omni"
            user = json_body["messages"][1]["content"]
            assert any(
                isinstance(part, dict)
                and part.get("type") == "image_url"
                and "data:image/png;base64," in part.get("image_url", {}).get("url", "")
                for part in user
            )
            return HttpResponseData(
                status=200,
                body_text=json.dumps({"choices": [{"message": {"content": "## OCR\n你好"}}]}),
            )

        service.http_client.request = fake_request
        text = await service.parse_image(filename="n.png", content=b"\x89PNG\r\n\x1a\n")
        assert "OCR" in text or "你好" in text

    asyncio.run(run())


def test_omni_parse_audio_uses_input_audio() -> None:
    async def run() -> None:
        service = OpenRouterOmniMediaParseService(api_key="k")

        async def fake_request(method, url, *, headers=None, json_body=None):
            user = json_body["messages"][1]["content"]
            audio_parts = [p for p in user if isinstance(p, dict) and p.get("type") == "input_audio"]
            assert len(audio_parts) == 1
            assert audio_parts[0]["input_audio"]["format"] == "mp3"
            assert audio_parts[0]["input_audio"]["data"]
            return HttpResponseData(
                status=200,
                body_text=json.dumps({"choices": [{"message": {"content": "转写：测试一句"}}]}),
            )

        service.http_client.request = fake_request
        text = await service.parse_audio(filename="a.mp3", content=b"\xff\xfb")
        assert "转写" in text

    asyncio.run(run())


def test_omni_parse_video_uses_video_url_data_uri() -> None:
    async def run() -> None:
        service = OpenRouterOmniMediaParseService(api_key="k")

        async def fake_request(method, url, *, headers=None, json_body=None):
            user = json_body["messages"][1]["content"]
            v = [p for p in user if isinstance(p, dict) and p.get("type") == "video_url"]
            assert len(v) == 1
            assert v[0]["video_url"]["url"].startswith("data:video/mp4;base64,")
            return HttpResponseData(
                status=200,
                body_text=json.dumps({"choices": [{"message": {"content": "视频摘要"}}]}),
            )

        service.http_client.request = fake_request
        text = await service.parse_video(filename="v.mp4", content=b"\x00\x00\x00 ftyp")
        assert "视频" in text

    asyncio.run(run())


def test_composite_prefers_omni_for_image_when_configured() -> None:
    async def run() -> None:
        from app.services.document_parse_router import CompositeDocumentParseService
        from app.services.mistral_document_parse import MistralDocumentParseService

        omni = OpenRouterOmniMediaParseService(api_key="ok")

        async def fake_omni_request(method, url, *, headers=None, json_body=None):
            return HttpResponseData(
                status=200,
                body_text=json.dumps({"choices": [{"message": {"content": "来自Omni的图片"}}]}),
            )

        omni.http_client.request = fake_omni_request
        mistral = MistralDocumentParseService(api_key="m")

        async def fail_mistral(*args, **kwargs):
            raise AssertionError("mistral image should not run when omni is configured")

        mistral.http_client.request = fail_mistral

        router = CompositeDocumentParseService(mistral=mistral, omni=omni)
        text = await router.parse_image(filename="x.png", content=b"x")
        assert "Omni" in text

    asyncio.run(run())
