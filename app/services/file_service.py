from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from app.providers.embedding_base import EmbeddingProviderBase
from app.services.d1_repo import AppRepository
from app.services.file_parser import FileParser
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore


class PdfParseService(Protocol):
    async def parse_pdf(self, *, filename: str, content: bytes) -> str: ...
    async def parse_image(self, *, filename: str, content: bytes) -> str: ...


class FileService:
    def __init__(
        self,
        repository: AppRepository,
        file_store: R2FileStore,
        file_parser: FileParser,
        embedding_provider: EmbeddingProviderBase,
        qdrant_store: QdrantStore,
        pdf_parse_service: PdfParseService | None = None,
        *,
        max_size_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.repository = repository
        self.file_store = file_store
        self.file_parser = file_parser
        self.embedding_provider = embedding_provider
        self.qdrant_store = qdrant_store
        self.pdf_parse_service = pdf_parse_service
        self.max_size_bytes = max_size_bytes

    async def upload_base64_file(
        self,
        *,
        client_id: str,
        filename: str,
        content_type: str,
        content_base64: str,
    ) -> dict:
        user = await self.repository.get_or_create_user(client_id)
        suffix = Path(filename).suffix.lower()
        if suffix not in self.file_parser.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {suffix}")
        try:
            content = base64.b64decode(content_base64.encode("utf-8"))
        except binascii.Error as exc:
            raise ValueError("Invalid base64 file payload") from exc
        if len(content) > self.max_size_bytes:
            raise ValueError(f"File exceeds max size of {self.max_size_bytes} bytes")

        r2_key = await self.file_store.save_file(filename, content)
        try:
            if suffix == ".pdf":
                if self.pdf_parse_service is None:
                    raise ValueError("PDF parsing service is not configured.")
                text = await self.pdf_parse_service.parse_pdf(filename=filename, content=content)
            elif suffix in {".png", ".jpg", ".jpeg"}:
                if self.pdf_parse_service is None:
                    raise ValueError("Image OCR service is not configured.")
                text = await self.pdf_parse_service.parse_image(filename=filename, content=content)
            else:
                text = self.file_parser.parse_text(filename, content)
        except Exception as exc:  # noqa: BLE001
            await self.file_store.delete_file(r2_key)
            raise ValueError(f"Failed to parse file: {exc}") from exc
        summary = self._build_summary(text)
        record = await self.repository.create_file(
            user.id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            r2_key=r2_key,
            summary=summary,
        )
        chunks = self.file_parser.chunk_document(filename, text)
        try:
            if chunks:
                vectors = await self.embedding_provider.embed(chunks)
                await self.qdrant_store.create_payload_index("user_id")
                await self.qdrant_store.create_payload_index("file_id")
                points = []
                for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
                    point_id = str(uuid5(NAMESPACE_URL, f"{record.id}:{index}"))
                    points.append(
                        {
                            "id": point_id,
                            "vector": vector,
                            "payload": {
                                "user_id": user.id,
                                "file_id": record.id,
                                "filename": record.filename,
                                "chunk_index": index,
                                "source_type": suffix.lstrip("."),
                                "text": chunk,
                            },
                        }
                    )
                await self.qdrant_store.upsert_chunks(points)
        except Exception:  # noqa: BLE001
            await self.repository.delete_file(user.id, record.id)
            await self.file_store.delete_file(r2_key)
            raise
        vector_count = await self.qdrant_store.count_by_file(user_id=user.id, file_id=record.id) if chunks else 0
        return {
            "user_id": user.id,
            "file": record.to_dict(),
            "chunk_count": len(chunks),
            "vector_count": vector_count,
        }

    async def delete_file(self, *, client_id: str, file_id: str) -> dict | None:
        user = await self.repository.get_or_create_user(client_id)
        record = await self.repository.delete_file(user.id, file_id)
        if not record:
            return None
        await self.qdrant_store.delete_by_file(user_id=user.id, file_id=file_id)
        await self.file_store.delete_file(record.r2_key)
        return record.to_dict()

    async def rename_file(self, *, client_id: str, file_id: str, filename: str) -> dict | None:
        user = await self.repository.get_or_create_user(client_id)
        current = await self.repository.get_file(user.id, file_id)
        if not current:
            return None
        next_name = filename.strip()
        if not next_name:
            raise ValueError("filename is required")
        if Path(current.filename).suffix.lower() != Path(next_name).suffix.lower():
            raise ValueError("Renaming must keep the same file extension")
        record = await self.repository.update_file_name(user.id, file_id, next_name)
        if record:
            await self.qdrant_store.update_file_metadata(user_id=user.id, file_id=file_id, updates={"filename": next_name})
        return record.to_dict() if record else None

    def _build_summary(self, text: str) -> str:
        compact = " ".join(text.split())
        return compact[:220]

    async def get_file_vector_count(self, *, user_id: str, file_id: str) -> int:
        return await self.qdrant_store.count_by_file(user_id=user_id, file_id=file_id)
