from __future__ import annotations

from app.services.http_client import HttpClient


class SearchService:
    def __init__(self, api_key: str | None = None, timeout_seconds: float = 12.0) -> None:
        self.api_key = api_key
        self.http_client = HttpClient(timeout_seconds=timeout_seconds)

    async def search(self, query: str) -> list[dict]:
        if not self.api_key:
            return [
                {
                    "title": "Search service not configured",
                    "url": "https://serper.dev",
                    "snippet": f"Configure SERPER_API_KEY to enable live web search for: {query}",
                }
            ]
        try:
            response = await self.http_client.request(
                "POST",
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.api_key},
                json_body={"q": query, "num": 5},
            )
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            return [
                {
                    "title": "Search request failed",
                    "url": "https://serper.dev",
                    "snippet": f"Serper request failed for '{query}': {exc}",
                }
            ]

        organic = body.get("organic", [])
        results = []
        for item in organic[:5]:
            results.append(
                {
                    "title": item.get("title", "Untitled result"),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
        if not results:
            results.append(
                {
                    "title": "No search results",
                    "url": "https://serper.dev",
                    "snippet": f"Serper returned no organic results for: {query}",
                }
            )
        return results
