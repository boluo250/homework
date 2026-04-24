from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse


@dataclass(slots=True)
class HttpRequest:
    method: str
    path: str
    headers: dict[str, str]
    query: dict[str, str]
    body: bytes = b""
    json_data: dict | list | None = None

    @classmethod
    def from_raw(
        cls,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> "HttpRequest":
        parsed = urlparse(url)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        data = None
        lowered_headers = {k.lower(): v for k, v in (headers or {}).items()}
        if body and "application/json" in lowered_headers.get("content-type", ""):
            data = json.loads(body.decode("utf-8"))
        return cls(
            method=method.upper(),
            path=parsed.path,
            headers=lowered_headers,
            query=query,
            body=body,
            json_data=data,
        )


@dataclass(slots=True)
class HttpResponse:
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    stream_chunks: Any = None

    @classmethod
    def json(cls, payload: dict | list, status: int = 200) -> "HttpResponse":
        return cls(
            status=status,
            headers={"content-type": "application/json; charset=utf-8"},
            body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    @classmethod
    def text(cls, payload: str, status: int = 200) -> "HttpResponse":
        return cls(
            status=status,
            headers={"content-type": "text/plain; charset=utf-8"},
            body=payload.encode("utf-8"),
        )

    @classmethod
    def html(cls, payload: str, status: int = 200) -> "HttpResponse":
        return cls(
            status=status,
            headers={"content-type": "text/html; charset=utf-8"},
            body=payload.encode("utf-8"),
        )

    @classmethod
    def sse(cls, events: list[bytes], status: int = 200) -> "HttpResponse":
        return cls(
            status=status,
            headers={
                "content-type": "text/event-stream; charset=utf-8",
                "cache-control": "no-cache, no-transform",
                "connection": "keep-alive",
            },
            body=b"".join(events),
            stream_chunks=events,
        )

    @classmethod
    def sse_stream(cls, stream_chunks: Any, status: int = 200) -> "HttpResponse":
        return cls(
            status=status,
            headers={
                "content-type": "text/event-stream; charset=utf-8",
                "cache-control": "no-cache, no-transform",
                "connection": "keep-alive",
            },
            body=b"",
            stream_chunks=stream_chunks,
        )
