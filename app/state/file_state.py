from __future__ import annotations

from app.core.models import FileRecord
from app.services.d1_repo import AppRepository


class FileState:
    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    async def create_file_record(
        self,
        user_id: str,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        r2_key: str,
        summary: str | None,
    ) -> FileRecord:
        return await self.repository.create_file(
            user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            r2_key=r2_key,
            summary=summary,
        )

    async def list_files(self, user_id: str) -> list[FileRecord]:
        return await self.repository.list_files(user_id)

    async def get_file(self, user_id: str, file_id: str) -> FileRecord | None:
        return await self.repository.get_file(user_id, file_id)

    async def rename_file(self, user_id: str, file_id: str, filename: str) -> FileRecord | None:
        return await self.repository.update_file_name(user_id, file_id, filename)

    async def delete_file(self, user_id: str, file_id: str) -> FileRecord | None:
        return await self.repository.delete_file(user_id, file_id)

    async def clear_files(self, user_id: str) -> list[FileRecord]:
        files = await self.list_files(user_id)
        deleted: list[FileRecord] = []
        for item in files:
            removed = await self.delete_file(user_id, item.id)
            if removed is not None:
                deleted.append(removed)
        return deleted
