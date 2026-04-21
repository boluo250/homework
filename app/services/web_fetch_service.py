from __future__ import annotations

import re

from app.services.http_client import HttpClient


class WebFetchService:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.http_client = HttpClient(timeout_seconds=timeout_seconds)

    async def fetch_text(self, url: str) -> str:
        try:
            response = await self.http_client.request(
                "GET",
                url,
                headers={"User-Agent": "TaskMateBot/0.1 (+https://example.com)"},
            )
            body = response.body_text
            if response.status >= 400:
                return ""
        except Exception:  # noqa: BLE001
            return ""
        return _extract_text(body)


def _extract_text(html: str) -> str:
    stripped = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    stripped = re.sub(r"<style.*?>.*?</style>", " ", stripped, flags=re.IGNORECASE | re.DOTALL)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    stripped = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&#39;|&quot;", " ", stripped)
    return re.sub(r"\s{2,}", " ", stripped).strip()
