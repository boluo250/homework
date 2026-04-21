from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


try:  # pragma: no cover
    from js import fetch  # type: ignore
    from pyodide.ffi import to_js as _to_js  # type: ignore
except ImportError:  # pragma: no cover
    fetch = None
    _to_js = None


@dataclass(slots=True)
class HttpResponseData:
    status: int
    body_text: str

    def json(self) -> Any:
        return json.loads(self.body_text)


class HttpClient:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict | list | None = None,
    ) -> HttpResponseData:
        payload = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        request_headers = dict(headers or {})
        if json_body is not None:
            request_headers.setdefault("Content-Type", "application/json")

        if fetch is not None and _to_js is not None:
            return await self._request_via_fetch(method, url, headers=request_headers, payload=payload)
        return self._request_via_urllib(method, url, headers=request_headers, payload=payload)

    async def _request_via_fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: bytes | None,
    ) -> HttpResponseData:
        options: dict[str, Any] = {"method": method, "headers": _to_js(headers)}
        if payload is not None:
            options["body"] = payload.decode("utf-8")
        response = await fetch(url, _to_js(options))
        body_text = await response.text()
        return HttpResponseData(status=int(response.status), body_text=str(body_text))

    def _request_via_urllib(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: bytes | None,
    ) -> HttpResponseData:
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return HttpResponseData(
                    status=response.getcode(),
                    body_text=response.read().decode("utf-8", errors="ignore"),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponseData(
                status=exc.code,
                body_text=exc.read().decode("utf-8", errors="ignore"),
            )
        except urllib.error.URLError as exc:
            raise RuntimeError(f"HTTP request failed: {exc}") from exc
