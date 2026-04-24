from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, AsyncIterator


try:  # pragma: no cover
    from js import AbortController, clearTimeout, fetch, setTimeout  # type: ignore
    from pyodide.ffi import to_js as _to_js  # type: ignore
except ImportError:  # pragma: no cover
    AbortController = None
    clearTimeout = None
    fetch = None
    setTimeout = None
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

    async def request_stream_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict | list | None = None,
    ) -> AsyncIterator[str]:
        payload = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        request_headers = dict(headers or {})
        if json_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        if fetch is None or _to_js is None:
            response = self._request_via_urllib(method, url, headers=request_headers, payload=payload)
            if response.body_text:
                yield response.body_text
            return
        async for chunk in self._request_via_fetch_stream(method, url, headers=request_headers, payload=payload):
            yield chunk

    async def _request_via_fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: bytes | None,
    ) -> HttpResponseData:
        options: dict[str, Any] = {"method": method, "headers": _to_js(headers)}
        timeout_id = None
        controller = None
        if AbortController is not None and setTimeout is not None:
            controller = AbortController.new()
            options["signal"] = controller.signal
            timeout_id = setTimeout(controller.abort, int(self.timeout_seconds * 1000))
        if payload is not None:
            options["body"] = payload.decode("utf-8")
        try:
            response = await fetch(url, _to_js(options))
            body_text = await response.text()
            return HttpResponseData(status=int(response.status), body_text=str(body_text))
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "AbortError" in message or "aborted" in message.lower():
                raise RuntimeError(f"HTTP request timed out after {self.timeout_seconds:.1f}s") from exc
            raise RuntimeError(f"HTTP request failed: {message}") from exc
        finally:
            if timeout_id is not None and clearTimeout is not None:
                clearTimeout(timeout_id)

    async def _request_via_fetch_stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: bytes | None,
    ) -> AsyncIterator[str]:
        options: dict[str, Any] = {"method": method, "headers": _to_js(headers)}
        timeout_id = None
        controller = None
        if AbortController is not None and setTimeout is not None:
            controller = AbortController.new()
            options["signal"] = controller.signal
            timeout_id = setTimeout(controller.abort, int(self.timeout_seconds * 1000))
        if payload is not None:
            options["body"] = payload.decode("utf-8")
        try:
            response = await fetch(url, _to_js(options))
            if int(response.status) >= 400:
                body_text = await response.text()
                raise RuntimeError(f"HTTP request failed with status {int(response.status)}: {str(body_text)[:300]}")
            body = getattr(response, "body", None)
            if body is None:
                text = await response.text()
                if text:
                    yield str(text)
                return
            import js  # type: ignore

            decoder = js.TextDecoder.new()
            reader = body.getReader()
            while True:
                result = await reader.read()
                if bool(result.done):
                    tail = str(decoder.decode())
                    if tail:
                        yield tail
                    break
                chunk = str(decoder.decode(result.value, _to_js({"stream": True})))
                if chunk:
                    yield chunk
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "AbortError" in message or "aborted" in message.lower():
                raise RuntimeError(f"HTTP request timed out after {self.timeout_seconds:.1f}s") from exc
            raise RuntimeError(f"HTTP request failed: {message}") from exc
        finally:
            if timeout_id is not None and clearTimeout is not None:
                clearTimeout(timeout_id)

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
