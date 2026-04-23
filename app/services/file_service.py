from __future__ import annotations

import asyncio
import base64
import binascii
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from app.providers.embedding_base import EmbeddingProviderBase
from app.services.d1_repo import AppRepository
from app.services.file_parser import FileParser
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".aiff", ".aif"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mpeg", ".mpg", ".m4v"}


def transcript_staging_object_key(file_id: str) -> str:
    """Stable R2 object key for video transcript staging between queue steps."""
    safe = file_id.replace("/", "_")
    return f"ingest-transcript-{safe}.txt"


# 视频在 Worker fetch 中解析易触发 CPU 限制；已配置 ingest 队列时仅入队，由消费者完成 MiMo 调用与向量化
MEDIA_INGEST_PENDING = "[ingest_pending]"
# 转写已完成、正文暂存 R2，等待第二条队列消息做 embedding（降低单次 invocation 的 CPU 峰值）
MEDIA_INGEST_STAGING_PREFIX = "[ingest_staging_r2]"
_EMBED_UPSERT_BATCH = 12


class PdfParseService(Protocol):
    async def parse_pdf(self, *, filename: str, content: bytes) -> str: ...
    async def parse_image(self, *, filename: str, content: bytes) -> str: ...
    async def parse_audio(self, *, filename: str, content: bytes) -> str: ...
    async def parse_video(self, *, filename: str, content: bytes) -> str: ...


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
        max_size_bytes: int = 10 * 1024 * 1024,
        ingest_queue: Any | None = None,
    ) -> None:
        self.repository = repository
        self.file_store = file_store
        self.file_parser = file_parser
        self.embedding_provider = embedding_provider
        self.qdrant_store = qdrant_store
        self.pdf_parse_service = pdf_parse_service
        self.max_size_bytes = max_size_bytes
        self.ingest_queue = ingest_queue

    async def _index_text_chunks(
        self,
        *,
        user_id: str,
        file_id: str,
        filename: str,
        suffix: str,
        text: str,
    ) -> tuple[int, int]:
        chunks = self.file_parser.chunk_document(filename, text)
        if not chunks:
            return 0, 0
        await self.qdrant_store.create_payload_index("user_id")
        await self.qdrant_store.create_payload_index("file_id")
        source_type = suffix.lstrip(".")
        total = len(chunks)
        for batch_start in range(0, total, _EMBED_UPSERT_BATCH):
            batch = chunks[batch_start : batch_start + _EMBED_UPSERT_BATCH]
            vectors = await self.embedding_provider.embed(batch)
            points = []
            for offset, (chunk, vector) in enumerate(zip(batch, vectors, strict=True)):
                index = batch_start + offset
                point_id = str(uuid5(NAMESPACE_URL, f"{file_id}:{index}"))
                points.append(
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": {
                            "user_id": user_id,
                            "file_id": file_id,
                            "filename": filename,
                            "chunk_index": index,
                            "source_type": source_type,
                            "text": chunk,
                        },
                    }
                )
            await self.qdrant_store.upsert_chunks(points)
            await asyncio.sleep(0)
        vector_count = await self.qdrant_store.count_by_file(user_id=user_id, file_id=file_id)
        return total, vector_count

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
            raise ValueError(f"File exceeds max size of {_format_size_mb(self.max_size_bytes)}")

        r2_key = await self.file_store.save_file(filename, content)
        deferred_video = False
        try:
            if suffix == ".pdf":
                if self.pdf_parse_service is None:
                    raise ValueError("PDF parsing service is not configured.")
                text = await self.pdf_parse_service.parse_pdf(filename=filename, content=content)
            elif suffix in _IMAGE_SUFFIXES:
                if self.pdf_parse_service is None:
                    raise ValueError("Image extraction service is not configured.")
                text = await self.pdf_parse_service.parse_image(filename=filename, content=content)
            elif suffix in _AUDIO_SUFFIXES:
                if self.pdf_parse_service is None:
                    raise ValueError("Audio extraction service is not configured.")
                text = await self.pdf_parse_service.parse_audio(filename=filename, content=content)
            elif suffix in _VIDEO_SUFFIXES:
                if self.pdf_parse_service is None:
                    raise ValueError("Video extraction service is not configured.")
                if self.ingest_queue is not None:
                    deferred_video = True
                    text = ""
                else:
                    text = await self.pdf_parse_service.parse_video(filename=filename, content=content)
            else:
                text = self.file_parser.parse_text(filename, content)
        except Exception as exc:  # noqa: BLE001
            await self.file_store.delete_file(r2_key)
            raise ValueError(f"Failed to parse file: {exc}") from exc

        summary = MEDIA_INGEST_PENDING if deferred_video else self._build_summary(text)
        record = await self.repository.create_file(
            user.id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            r2_key=r2_key,
            summary=summary,
        )
        try:
            if deferred_video:
                await self.ingest_queue.send(
                    json.dumps(
                        {"type": "file_media_ingest", "file_id": record.id, "user_id": user.id},
                        ensure_ascii=False,
                    )
                )
                chunk_count, vector_count = 0, 0
            else:
                chunk_count, vector_count = await self._index_text_chunks(
                    user_id=user.id,
                    file_id=record.id,
                    filename=record.filename,
                    suffix=suffix,
                    text=text,
                )
        except Exception:  # noqa: BLE001
            await self.repository.delete_file(user.id, record.id)
            await self.file_store.delete_file(r2_key)
            raise

        payload: dict[str, Any] = {
            "user_id": user.id,
            "file": record.to_dict(),
            "chunk_count": chunk_count,
            "vector_count": vector_count,
        }
        if deferred_video:
            payload["ingest_status"] = "queued"
        return payload

    async def process_queued_media_ingest(self, *, user_id: str, file_id: str) -> None:
        """Queue 消费者：从 R2 读回视频，调用多模态解析；若配置了 ingest 队列则只转写并入队 embedding，否则本函数内直接向量化。"""
        record = await self.repository.get_file(user_id, file_id)
        if not record:
            raise ValueError(f"file not found: {file_id}")
        if (record.summary or "").strip() != MEDIA_INGEST_PENDING:
            return
        suffix = Path(record.filename).suffix.lower()
        if suffix not in _VIDEO_SUFFIXES:
            return
        if self.pdf_parse_service is None:
            raise ValueError("Video extraction service is not configured.")
        content = await self.file_store.read_file(record.r2_key)
        text = await self.pdf_parse_service.parse_video(filename=record.filename, content=content)
        if self.ingest_queue is not None:
            staging_key = await self._write_transcript_staging(file_id=file_id, text=text)
            await self.repository.update_file_summary(
                user_id, file_id, summary=f"{MEDIA_INGEST_STAGING_PREFIX}{staging_key}"
            )
            await self.ingest_queue.send(
                json.dumps(
                    {"type": "file_media_embed", "file_id": file_id, "user_id": user_id},
                    ensure_ascii=False,
                )
            )
            return
        await self._finalize_media_index(
            user_id=user_id,
            file_id=file_id,
            filename=record.filename,
            suffix=suffix,
            text=text,
            staging_r2_key=None,
        )

    async def process_queued_media_embed(self, *, user_id: str, file_id: str) -> None:
        """第二条队列消息：读回暂存转写文本，分批 embedding 并写入 Qdrant。"""
        record = await self.repository.get_file(user_id, file_id)
        if not record:
            raise ValueError(f"file not found: {file_id}")
        summary = (record.summary or "").strip()
        if not summary.startswith(MEDIA_INGEST_STAGING_PREFIX):
            return
        staging_r2_key = summary[len(MEDIA_INGEST_STAGING_PREFIX) :].strip()
        if not staging_r2_key:
            await self.mark_media_ingest_failed(user_id=user_id, file_id=file_id, error_message="missing staging r2 key")
            return
        try:
            raw = await self.file_store.read_file(staging_r2_key)
            text = raw.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            await self.mark_media_ingest_failed(
                user_id=user_id, file_id=file_id, error_message=f"read transcript staging failed: {exc}"
            )
            return
        suffix = Path(record.filename).suffix.lower()
        await self._finalize_media_index(
            user_id=user_id,
            file_id=file_id,
            filename=record.filename,
            suffix=suffix,
            text=text,
            staging_r2_key=staging_r2_key,
        )

    async def _write_transcript_staging(self, *, file_id: str, text: str) -> str:
        if not hasattr(self.file_store, "save_bytes_with_object_key"):
            raise RuntimeError("file_store does not support save_bytes_with_object_key")
        object_key = transcript_staging_object_key(file_id)
        return await self.file_store.save_bytes_with_object_key(object_key, text.encode("utf-8"))

    async def _finalize_media_index(
        self,
        *,
        user_id: str,
        file_id: str,
        filename: str,
        suffix: str,
        text: str,
        staging_r2_key: str | None,
    ) -> None:
        await self._index_text_chunks(
            user_id=user_id,
            file_id=file_id,
            filename=filename,
            suffix=suffix,
            text=text,
        )
        final_summary = self._build_summary(text) if text.strip() else "[ingest_empty]"
        await self.repository.update_file_summary(user_id, file_id, summary=final_summary)
        if staging_r2_key:
            try:
                await self.file_store.delete_file(staging_r2_key)
            except Exception:  # noqa: BLE001
                pass

    async def _delete_transcript_staging_best_effort(self, *, file_id: str) -> None:
        bucket = getattr(self.file_store, "bucket_name", None) or "local-r2"
        key = transcript_staging_object_key(file_id)
        try:
            await self.file_store.delete_file(f"r2://{bucket}/{key}")
        except Exception:  # noqa: BLE001
            pass

    async def mark_media_ingest_failed(self, *, user_id: str, file_id: str, error_message: str) -> None:
        snippet = (error_message or "").replace("\n", " ").strip()[:200]
        await self.repository.update_file_summary(
            user_id,
            file_id,
            summary=f"[ingest_failed] {snippet}" if snippet else "[ingest_failed]",
        )

    async def delete_file(self, *, client_id: str, file_id: str) -> dict | None:
        user = await self.repository.get_or_create_user(client_id)
        record = await self.repository.delete_file(user.id, file_id)
        if not record:
            return None
        await self.qdrant_store.delete_by_file(user_id=user.id, file_id=file_id)
        await self.file_store.delete_file(record.r2_key)
        await self._delete_transcript_staging_best_effort(file_id=file_id)
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

    async def get_file_detail(self, *, client_id: str, file_id: str) -> dict | None:
        user = await self.repository.get_or_create_user(client_id)
        return await self.get_file_detail_for_user(user_id=user.id, file_id=file_id)

    async def get_file_detail_for_user(self, *, user_id: str, file_id: str) -> dict | None:
        record = await self.repository.get_file(user_id, file_id)
        if not record:
            return None

        vector_count = await self.qdrant_store.count_by_file(user_id=user_id, file_id=file_id)
        chunks = await self.qdrant_store.list_chunks_by_file(user_id=user_id, file_id=file_id, limit=6)
        preview_text = self._build_preview_text(chunks=chunks, summary=record.summary)

        return {
            "file": record.to_dict(),
            "vector_count": vector_count,
            "preview_text": preview_text,
            "preview_truncated": len(preview_text) >= 1600,
        }

    def _build_summary(self, text: str) -> str:
        compact = " ".join(text.split())
        return compact[:220]

    def _build_preview_text(self, *, chunks: list[dict], summary: str | None) -> str:
        parts: list[str] = []
        total_chars = 0
        for chunk in chunks:
            payload = chunk.get("payload", {})
            text = str(payload.get("text", "")).strip()
            if not text:
                continue
            remaining = 1600 - total_chars
            if remaining <= 0:
                break
            snippet = text[:remaining].strip()
            if snippet:
                parts.append(snippet)
                total_chars += len(snippet)
            if total_chars >= 1600:
                break

        if parts:
            return "\n\n".join(parts)
        return (summary or "").strip()

    async def get_file_vector_count(self, *, user_id: str, file_id: str) -> int:
        return await self.qdrant_store.count_by_file(user_id=user_id, file_id=file_id)


def _format_size_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.0f} MB"
