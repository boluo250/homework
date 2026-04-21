from __future__ import annotations

from pathlib import Path
from uuid import uuid4


class R2FileStore:
    def __init__(self, root_dir: Path, bucket_name: str | None = None) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.bucket_name = bucket_name or "local-r2"

    async def save_file(self, filename: str, content: bytes) -> str:
        key = f"{uuid4().hex[:12]}-{filename}"
        path = self.root_dir / key
        path.write_bytes(content)
        return f"r2://{self.bucket_name}/{key}"

    async def read_file(self, r2_key: str) -> bytes:
        path = self._resolve_path(r2_key)
        return path.read_bytes()

    async def delete_file(self, r2_key: str) -> None:
        path = self._resolve_path(r2_key)
        if path.exists():
            path.unlink()

    async def delete_all_files(self) -> None:
        for path in self.root_dir.iterdir():
            if path.is_file():
                path.unlink()

    def _resolve_path(self, r2_key: str) -> Path:
        key = r2_key.rsplit("/", 1)[-1]
        return self.root_dir / key
