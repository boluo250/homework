from __future__ import annotations

import json

from app.services.http_client import HttpClient

SERPER_API_URL = "https://google.serper.dev/search"
SERPER_DOCS_URL = "https://serper.dev"
DEFAULT_RESULT_LIMIT = 5


class SearchService:
    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float = 12.0,
        *,
        http_client: HttpClient | None = None,
        default_region: str | None = None,
        default_locale: str | None = None,
        default_limit: int = DEFAULT_RESULT_LIMIT,
    ) -> None:
        self.api_key = api_key
        self.http_client = http_client or HttpClient(timeout_seconds=timeout_seconds)
        self.default_region = (default_region or "").strip() or None
        self.default_locale = (default_locale or "").strip() or None
        self.default_limit = max(1, min(int(default_limit or DEFAULT_RESULT_LIMIT), 10))

    async def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        region: str | None = None,
        locale: str | None = None,
    ) -> list[dict]:
        normalized_query = query.strip()
        result_limit = max(1, min(int(limit or self.default_limit), 10))
        self._log(
            "search.start",
            provider="serper",
            query=normalized_query,
            limit=result_limit,
            region=(region or self.default_region or "").strip() or None,
            locale=(locale or self.default_locale or "").strip() or None,
            api_key_configured=bool(self.api_key),
        )
        if not self.api_key:
            results = [
                self._status_result("config_missing", f"Configure SERPER_API_KEY to enable live web search for: {normalized_query}")
            ]
            self._log("search.done", provider="serper", query=normalized_query, status="config_missing", result_count=len(results))
            return results
        payload = {"q": normalized_query, "num": result_limit}
        resolved_region = (region or self.default_region or "").strip()
        resolved_locale = (locale or self.default_locale or "").strip()
        if resolved_region:
            payload["gl"] = resolved_region
        if resolved_locale:
            payload["hl"] = resolved_locale
        try:
            response = await self.http_client.request(
                "POST",
                SERPER_API_URL,
                headers={"X-API-KEY": self.api_key},
                json_body=payload,
            )
            if response.status >= 400:
                results = [
                    self._status_result(
                        "http_error",
                        f"Serper returned HTTP {response.status} for '{normalized_query}'.",
                    )
                ]
                self._log(
                    "search.done",
                    provider="serper",
                    query=normalized_query,
                    status="http_error",
                    http_status=response.status,
                    result_count=len(results),
                )
                return results
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            results = [self._status_result("request_failed", f"Serper request failed for '{normalized_query}': {exc}")]
            self._log(
                "search.done",
                provider="serper",
                query=normalized_query,
                status="request_failed",
                error=str(exc)[:500],
                result_count=len(results),
            )
            return results

        organic = body.get("organic", [])
        results = []
        for item in organic[:result_limit]:
            results.append(
                {
                    "title": item.get("title", "Untitled result"),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "provider": "serper",
                    "status": "ok",
                    "is_live_result": True,
                }
            )
        if not results:
            results.append(self._status_result("no_results", f"Serper returned no organic results for: {normalized_query}"))
        self._log(
            "search.done",
            provider="serper",
            query=normalized_query,
            status=results[0].get("status", "ok"),
            result_count=len(results),
            organic_count=len(organic),
        )
        return results

    def _status_result(self, status: str, snippet: str) -> dict:
        titles = {
            "config_missing": "Search service not configured",
            "request_failed": "Search request failed",
            "http_error": "Search request was rejected",
            "no_results": "No search results",
        }
        return {
            "title": titles.get(status, "Search status"),
            "url": SERPER_DOCS_URL,
            "snippet": snippet,
            "provider": "serper",
            "status": status,
            "is_live_result": False,
        }

    def _log(self, event: str, **fields: object) -> None:
        payload = {"scope": "search", "event": event, **fields}
        try:
            print(f"[taskmate] {json.dumps(payload, ensure_ascii=False, default=str)}")
        except Exception:  # noqa: BLE001
            print(f"[taskmate] search event={event} fields={fields!r}")
