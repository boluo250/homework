import asyncio
import base64
import json
from types import SimpleNamespace

from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.services.d1_repo import InMemoryAppRepository
from app.services.file_parser import FileParser
from app.services.file_service import MEDIA_INGEST_PENDING, FileService
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore


class FakeIngestQueue:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, body: str) -> None:
        self.messages.append(body)


def test_video_upload_with_queue_does_not_call_parse_inline(tmp_path) -> None:
    async def run() -> None:
        q = FakeIngestQueue()
        parse = SimpleNamespace(
            parse_pdf=lambda **kw: _async_fail("pdf"),
            parse_image=lambda **kw: _async_fail("image"),
            parse_audio=lambda **kw: _async_fail("audio"),
            parse_video=lambda **kw: _async_fail("should not sync-parse video"),
        )
        service = FileService(
            repository=InMemoryAppRepository(),
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            pdf_parse_service=parse,
            ingest_queue=q,
        )
        payload = await service.upload_base64_file(
            client_id="c1",
            filename="clip.mp4",
            content_type="video/mp4",
            content_base64=base64.b64encode(b"not-really-mp4").decode(),
        )
        assert payload["ingest_status"] == "queued"
        assert payload["chunk_count"] == 0
        assert payload["vector_count"] == 0
        assert len(q.messages) == 1
        body = json.loads(q.messages[0])
        assert body["type"] == "file_media_ingest"
        assert body["file_id"] == payload["file"]["id"]
        assert body["user_id"] == payload["user_id"]
        rec = await service.repository.get_file(payload["user_id"], payload["file"]["id"])
        assert rec is not None
        assert rec.summary == MEDIA_INGEST_PENDING

    asyncio.run(run())


def test_process_queued_media_ingest_writes_vectors(tmp_path) -> None:
    async def run() -> None:
        repo = InMemoryAppRepository()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        parse = SimpleNamespace(
            parse_pdf=lambda **kw: _async_fail("pdf"),
            parse_image=lambda **kw: _async_fail("image"),
            parse_audio=lambda **kw: _async_fail("audio"),
            parse_video=lambda *, filename, content: _async_value("视频里说了：TaskMate 队列测试"),
        )
        service = FileService(
            repository=repo,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
            pdf_parse_service=parse,
            ingest_queue=None,
        )
        up = await service.upload_base64_file(
            client_id="c2",
            filename="x.mp4",
            content_type="video/mp4",
            content_base64=base64.b64encode(b"x").decode(),
        )
        assert "ingest_status" not in up
        await repo.update_file_summary(up["user_id"], up["file"]["id"], summary=MEDIA_INGEST_PENDING)
        await service.process_queued_media_ingest(user_id=up["user_id"], file_id=up["file"]["id"])
        rec = await repo.get_file(up["user_id"], up["file"]["id"])
        assert rec is not None
        assert rec.summary != MEDIA_INGEST_PENDING
        assert "TaskMate" in (rec.summary or "")
        n = await qdrant.count_by_file(user_id=up["user_id"], file_id=up["file"]["id"])
        assert n >= 1

    asyncio.run(run())


async def _async_value(value: str) -> str:
    return value


async def _async_fail(msg: str) -> str:
    raise AssertionError(msg)


def test_video_ingest_two_phase_queues_embed_then_vectors(tmp_path) -> None:
    async def run() -> None:
        q = FakeIngestQueue()
        repo = InMemoryAppRepository()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        parse = SimpleNamespace(
            parse_pdf=lambda **kw: _async_fail("pdf"),
            parse_image=lambda **kw: _async_fail("image"),
            parse_audio=lambda **kw: _async_fail("audio"),
            parse_video=lambda *, filename, content: _async_value("视频里说了：两阶段 ingest 测试"),
        )
        service = FileService(
            repository=repo,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
            pdf_parse_service=parse,
            ingest_queue=q,
        )
        up = await service.upload_base64_file(
            client_id="c3",
            filename="two.mp4",
            content_type="video/mp4",
            content_base64=base64.b64encode(b"x").decode(),
        )
        assert len(q.messages) == 1
        await service.process_queued_media_ingest(user_id=up["user_id"], file_id=up["file"]["id"])
        assert len(q.messages) == 2
        body2 = json.loads(q.messages[1])
        assert body2["type"] == "file_media_embed"
        await service.process_queued_media_embed(user_id=up["user_id"], file_id=up["file"]["id"])
        n = await qdrant.count_by_file(user_id=up["user_id"], file_id=up["file"]["id"])
        assert n >= 1

    asyncio.run(run())
