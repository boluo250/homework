import asyncio

from app.services.http_client import HttpResponseData
from app.services.search_service import SearchService
from app.services.web_fetch_service import _extract_text


def test_search_service_fallback_returns_result() -> None:
    async def run() -> None:
        service = SearchService(api_key=None)
        results = await service.search("latest cloudflare workers update")
        assert results
        assert "title" in results[0]
        assert results[0]["status"] == "config_missing"
        assert results[0]["is_live_result"] is False

    asyncio.run(run())


def test_search_service_uses_serper_adapter_and_normalizes_results() -> None:
    class FakeHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def request(self, method: str, url: str, *, headers=None, json_body=None):
            self.calls.append(
                {
                    "method": method,
                    "url": url,
                    "headers": headers or {},
                    "json_body": json_body or {},
                }
            )
            return HttpResponseData(
                status=200,
                body_text=(
                    '{"organic": ['
                    '{"title": "Cloudflare Workers", "link": "https://developers.cloudflare.com/workers/", "snippet": "Deploy serverless code."},'
                    '{"title": "Queues", "link": "https://developers.cloudflare.com/queues/", "snippet": "Background jobs."}'
                    "]} "
                ),
            )

    async def run() -> None:
        fake_http = FakeHttpClient()
        service = SearchService(
            api_key="test-key",
            http_client=fake_http,
            default_region="us",
            default_locale="en",
        )

        results = await service.search("cloudflare workers", limit=2)

        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["method"] == "POST"
        assert call["url"] == "https://google.serper.dev/search"
        assert call["headers"]["X-API-KEY"] == "test-key"
        assert call["json_body"] == {"q": "cloudflare workers", "num": 2, "gl": "us", "hl": "en"}

        assert [item["title"] for item in results] == ["Cloudflare Workers", "Queues"]
        assert all(item["provider"] == "serper" for item in results)
        assert all(item["status"] == "ok" for item in results)
        assert all(item["is_live_result"] is True for item in results)

    asyncio.run(run())


def test_extract_text_removes_html_noise() -> None:
    html = """
    <html>
      <head><style>.x { color: red; }</style></head>
      <body>
        <script>console.log('ignore')</script>
        <main><h1>Hello</h1><p>Cloudflare Worker text.</p></main>
      </body>
    </html>
    """
    text = _extract_text(html)
    assert "Hello" in text
    assert "Cloudflare Worker text." in text
