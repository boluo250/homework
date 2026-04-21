from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.services.http_client import HttpClient


@dataclass(slots=True)
class SearchMatch:
    text: str
    score: float
    payload: dict


class QdrantStore:
    def __init__(
        self,
        storage_path: Path | None = None,
        collection_name: str = "document_chunks",
        *,
        remote_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.storage_path = storage_path
        self.remote_url = remote_url.rstrip("/") if remote_url else None
        self.api_key = api_key
        self.http_client = HttpClient(timeout_seconds=20.0)
        self.payload_indexes: set[str] = set()
        self._remote_collection_ready = False
        if self.storage_path is not None:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.storage_path.exists():
                self.storage_path.write_text("[]", encoding="utf-8")

    async def create_payload_index(self, field_name: str) -> None:
        if self.remote_url:
            await self._ensure_remote_collection(vector_size=16)
            response = await self.http_client.request(
                "PUT",
                f"{self.remote_url}/collections/{self.collection_name}/index",
                headers=self._headers(),
                json_body={"field_name": field_name, "field_schema": "keyword"},
            )
            self._ensure_remote_ok(response, f"create payload index '{field_name}'")
        self.payload_indexes.add(field_name)

    async def upsert_chunks(self, chunks: list[dict]) -> int:
        if self.remote_url:
            if not chunks:
                return 0
            await self._ensure_remote_collection(vector_size=len(chunks[0]["vector"]))
            response = await self.http_client.request(
                "PUT",
                f"{self.remote_url}/collections/{self.collection_name}/points?wait=true",
                headers=self._headers(),
                json_body={"points": chunks},
            )
            self._ensure_remote_ok(response, f"upsert {len(chunks)} Qdrant chunks")
            return len(chunks)
        items = self._load()
        index_by_id = {_point_id(item): item for item in items}
        for chunk in chunks:
            index_by_id[_point_id(chunk)] = chunk
        self._save(list(index_by_id.values()))
        return len(chunks)

    async def search(self, *, query_vector: list[float], filters: dict, limit: int = 5) -> list[SearchMatch]:
        if self.remote_url:
            await self._ensure_remote_collection(vector_size=len(query_vector))
            response = await self.http_client.request(
                "POST",
                f"{self.remote_url}/collections/{self.collection_name}/points/search",
                headers=self._headers(),
                json_body={
                    "vector": query_vector,
                    "limit": limit,
                    "with_payload": True,
                    "filter": _build_remote_filter(filters),
                },
            )
            self._ensure_remote_ok(response, "search Qdrant chunks")
            body = response.json()
            results = body.get("result", [])
            return [
                SearchMatch(
                    text=item.get("payload", {}).get("text", ""),
                    score=float(item.get("score", 0.0)),
                    payload=item.get("payload", {}),
                )
                for item in results
            ]
        matches: list[SearchMatch] = []
        for item in self._load():
            if not _matches_filters(item["payload"], filters):
                continue
            score = _cosine_similarity(query_vector, item["vector"])
            matches.append(
                SearchMatch(
                    text=item["payload"].get("text", item.get("text", "")),
                    score=score,
                    payload=item["payload"],
                )
            )
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]

    async def delete_by_file(self, *, user_id: str, file_id: str) -> None:
        if self.remote_url:
            await self._ensure_remote_collection(vector_size=16)
            response = await self.http_client.request(
                "POST",
                f"{self.remote_url}/collections/{self.collection_name}/points/delete?wait=true",
                headers=self._headers(),
                json_body={
                    "filter": {
                        "must": [
                            {"key": "user_id", "match": {"value": user_id}},
                            {"key": "file_id", "match": {"value": file_id}},
                        ]
                    }
                },
            )
            self._ensure_remote_ok(response, f"delete Qdrant chunks for file {file_id}")
            return
        items = [
            item
            for item in self._load()
            if not (item["payload"].get("user_id") == user_id and item["payload"].get("file_id") == file_id)
        ]
        self._save(items)

    async def update_file_metadata(self, *, user_id: str, file_id: str, updates: dict) -> None:
        if self.remote_url:
            await self._ensure_remote_collection(vector_size=16)
            response = await self.http_client.request(
                "POST",
                f"{self.remote_url}/collections/{self.collection_name}/points/payload?wait=true",
                headers=self._headers(),
                json_body={
                    "payload": updates,
                    "filter": {
                        "must": [
                            {"key": "user_id", "match": {"value": user_id}},
                            {"key": "file_id", "match": {"value": file_id}},
                        ]
                    },
                },
            )
            self._ensure_remote_ok(response, f"update Qdrant payload for file {file_id}")
            return
        items = self._load()
        for item in items:
            payload = item.get("payload", {})
            if payload.get("user_id") == user_id and payload.get("file_id") == file_id:
                payload.update(updates)
        self._save(items)

    async def reset_collection(self) -> None:
        if self.remote_url:
            response = await self.http_client.request(
                "DELETE",
                f"{self.remote_url}/collections/{self.collection_name}",
                headers=self._headers(),
            )
            if response.status not in (200, 202, 404):
                self._ensure_remote_ok(response, f"reset Qdrant collection '{self.collection_name}'")
            self._remote_collection_ready = False
            self.payload_indexes.clear()
            return
        self._save([])
        self.payload_indexes.clear()

    async def count_by_file(self, *, user_id: str, file_id: str) -> int:
        if self.remote_url:
            await self._ensure_remote_collection(vector_size=16)
            response = await self.http_client.request(
                "POST",
                f"{self.remote_url}/collections/{self.collection_name}/points/count",
                headers=self._headers(),
                json_body={
                    "exact": True,
                    "filter": {
                        "must": [
                            {"key": "user_id", "match": {"value": user_id}},
                            {"key": "file_id", "match": {"value": file_id}},
                        ]
                    },
                },
            )
            self._ensure_remote_ok(response, f"count Qdrant chunks for file {file_id}")
            body = response.json()
            result = body.get("result", {})
            return int(result.get("count", 0))
        return sum(
            1
            for item in self._load()
            if item["payload"].get("user_id") == user_id and item["payload"].get("file_id") == file_id
        )

    async def list_chunks_by_file(self, *, user_id: str, file_id: str, limit: int = 24) -> list[dict]:
        if self.remote_url:
            await self._ensure_remote_collection(vector_size=16)
            response = await self.http_client.request(
                "POST",
                f"{self.remote_url}/collections/{self.collection_name}/points/scroll",
                headers=self._headers(),
                json_body={
                    "limit": limit,
                    "with_payload": True,
                    "with_vector": False,
                    "filter": {
                        "must": [
                            {"key": "user_id", "match": {"value": user_id}},
                            {"key": "file_id", "match": {"value": file_id}},
                        ]
                    },
                },
            )
            self._ensure_remote_ok(response, f"list Qdrant chunks for file {file_id}")
            body = response.json()
            result = body.get("result", {})
            points = result.get("points", []) if isinstance(result, dict) else []
            normalized = [
                {
                    "id": item.get("id"),
                    "payload": item.get("payload", {}),
                }
                for item in points
            ]
            normalized.sort(key=lambda item: int(item.get("payload", {}).get("chunk_index", 0)))
            return normalized
        items = [
            item
            for item in self._load()
            if item["payload"].get("user_id") == user_id and item["payload"].get("file_id") == file_id
        ]
        items.sort(key=lambda item: int(item.get("payload", {}).get("chunk_index", 0)))
        return items[:limit]

    async def _ensure_remote_collection(self, *, vector_size: int) -> None:
        if self._remote_collection_ready:
            return
        response = await self.http_client.request(
            "PUT",
            f"{self.remote_url}/collections/{self.collection_name}",
            headers=self._headers(),
            json_body={"vectors": {"size": vector_size, "distance": "Cosine"}},
        )
        if response.status != 409:
            self._ensure_remote_ok(response, f"ensure Qdrant collection '{self.collection_name}'")
        self._remote_collection_ready = True

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    def _load(self) -> list[dict]:
        if self.storage_path is None:
            return []
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _save(self, payload: list[dict]) -> None:
        if self.storage_path is None:
            return
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_remote_ok(self, response, operation: str) -> None:
        if response.status < 400:
            return
        snippet = response.body_text[:300].strip()
        raise RuntimeError(f"Qdrant failed to {operation} (HTTP {response.status}): {snippet}")


def _matches_filters(payload: dict, filters: dict) -> bool:
    for key, expected in filters.items():
        actual = payload.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _build_remote_filter(filters: dict) -> dict:
    must = []
    should = []
    for key, expected in filters.items():
        if isinstance(expected, list):
            for item in expected:
                should.append({"key": key, "match": {"value": item}})
        else:
            must.append({"key": key, "match": {"value": expected}})
    payload: dict[str, list] = {"must": must}
    if should:
        payload["should"] = should
    return payload


def _point_id(item: dict) -> str:
    point_id = item.get("id") or item.get("point_id")
    if not point_id:
        raise KeyError("Qdrant point is missing 'id'")
    return str(point_id)
