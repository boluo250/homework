import asyncio

from app.services.search_service import SearchService
from app.services.web_fetch_service import _extract_text


def test_search_service_fallback_returns_result() -> None:
    async def run() -> None:
        service = SearchService(api_key=None)
        results = await service.search("latest cloudflare workers update")
        assert results
        assert "title" in results[0]

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
