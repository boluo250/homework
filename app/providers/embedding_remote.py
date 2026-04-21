from __future__ import annotations

import hashlib

from app.services.http_client import HttpClient

from .embedding_base import EmbeddingProviderBase


class RemoteEmbeddingProvider(EmbeddingProviderBase):
    """Remote embedding provider with deterministic local fallback."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        endpoint_url: str | None = None,
        dimension: int = 16,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint_url = endpoint_url
        self.dimension = dimension
        self.http_client = HttpClient(timeout_seconds=timeout_seconds)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.api_key and self.endpoint_url:
            try:
                return await self._embed_remote(texts)
            except Exception:
                pass
        return self._embed_local(texts)

    async def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        response = await self.http_client.request(
            "POST",
            self.endpoint_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json_body={"model": self.model, "input": texts},
        )
        if response.status >= 400:
            raise RuntimeError(f"Embedding request failed with HTTP {response.status}: {response.body_text[:240]}")
        body = response.json()
        data = body.get("data") or body.get("embeddings") or []
        vectors: list[list[float]] = []
        for item in data:
            if isinstance(item, dict):
                vector = item.get("embedding")
            else:
                vector = item
            if not isinstance(vector, list):
                raise ValueError("Embedding response is missing numeric vectors")
            vectors.append([float(value) for value in vector])
        if len(vectors) != len(texts):
            raise ValueError("Embedding response count does not match input count")
        return vectors

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = []
            for index in range(self.dimension):
                values.append(round(digest[index] / 255.0, 6))
            vectors.append(values)
        return vectors
