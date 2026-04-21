from __future__ import annotations

from typing import Any
from uuid import uuid4


class CloudflareR2FileStore:
    def __init__(self, bucket: Any, bucket_name: str = "files-bucket") -> None:
        self.bucket = bucket
        self.bucket_name = bucket_name

    async def save_file(self, filename: str, content: bytes) -> str:
        key = f"{uuid4().hex[:12]}-{filename}"
        # Convert Python bytes to JS Uint8Array for R2
        try:
            import js
            uint8_array = js.Uint8Array.new(len(content))
            uint8_array.assign(content)
            await self.bucket.put(key, uint8_array)
        except ImportError:
            # Fallback for non-Pyodide environments
            await self.bucket.put(key, content)
        return f"r2://{self.bucket_name}/{key}"

    async def read_file(self, r2_key: str) -> bytes:
        key = r2_key.rsplit("/", 1)[-1]
        obj = await self.bucket.get(key)
        if not obj:
            raise FileNotFoundError(r2_key)
        if hasattr(obj, "arrayBuffer"):
            buffer = await obj.arrayBuffer()
            if hasattr(buffer, "to_py"):
                return bytes(buffer.to_py())
        if hasattr(obj, "text"):
            text = await obj.text()
            return str(text).encode("utf-8")
        raise FileNotFoundError(r2_key)

    async def delete_file(self, r2_key: str) -> None:
        key = r2_key.rsplit("/", 1)[-1]
        await self.bucket.delete(key)

    async def delete_all_files(self) -> int:
        deleted = 0
        cursor = None
        while True:
            page = await self.bucket.list({"cursor": cursor} if cursor else {})
            payload = page.to_py() if hasattr(page, "to_py") else page
            objects = payload.get("objects", []) if isinstance(payload, dict) else []
            for item in objects:
                key = item.get("key")
                if not key:
                    continue
                await self.bucket.delete(key)
                deleted += 1
            truncated = bool(payload.get("truncated")) if isinstance(payload, dict) else False
            cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if not truncated:
                break
        return deleted
