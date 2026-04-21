import asyncio
import base64
from types import SimpleNamespace

from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.services.d1_repo import InMemoryAppRepository
from app.services.file_parser import FileParser
from app.services.file_service import FileService
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore
from app.services.rag_service import RagService


def test_file_delete_removes_vectors(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
        )
        uploaded = await service.upload_base64_file(
            client_id="client_cleanup",
            filename="cleanup.txt",
            content_type="text/plain",
            content_base64=base64.b64encode(b"Cloudflare cleanup test").decode(),
        )
        rag = RagService(RemoteEmbeddingProvider(), qdrant)
        before = await rag.retrieve(
            user_id=uploaded["user_id"],
            query="cleanup",
            file_ids=[uploaded["file"]["id"]],
        )
        await service.delete_file(client_id="client_cleanup", file_id=uploaded["file"]["id"])
        after = await rag.retrieve(
            user_id=uploaded["user_id"],
            query="cleanup",
            file_ids=[uploaded["file"]["id"]],
        )
        assert before
        assert not after

    asyncio.run(run())


def test_pdf_upload_uses_external_parse_service(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            pdf_parse_service=SimpleNamespace(
                parse_pdf=lambda *, filename, content: _async_value("姓名：小李\n技能：Python\n经历：Cloudflare Worker")
            ),
        )
        uploaded = await service.upload_base64_file(
            client_id="client_pdf",
            filename="resume.pdf",
            content_type="application/pdf",
            content_base64=base64.b64encode(b"%PDF-pretend").decode(),
        )
        files = await repository.list_files(uploaded["user_id"])
        assert uploaded["chunk_count"] >= 1
        assert files[0].summary is not None
        assert "姓名" in files[0].summary

    asyncio.run(run())


def test_file_rename_updates_metadata_and_vectors(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
        )
        uploaded = await service.upload_base64_file(
            client_id="client_rename",
            filename="resume.txt",
            content_type="text/plain",
            content_base64=base64.b64encode(b"Agent experience and Cloudflare Worker project").decode(),
        )
        renamed = await service.rename_file(
            client_id="client_rename",
            file_id=uploaded["file"]["id"],
            filename="profile.txt",
        )
        assert renamed is not None
        assert renamed["filename"] == "profile.txt"
        chunks = await qdrant.list_chunks_by_file(user_id=uploaded["user_id"], file_id=uploaded["file"]["id"])
        assert chunks
        assert all(chunk["payload"].get("filename") == "profile.txt" for chunk in chunks)

    asyncio.run(run())


def test_image_upload_uses_external_ocr_service(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            pdf_parse_service=SimpleNamespace(
                parse_pdf=lambda *, filename, content: _async_value(""),
                parse_image=lambda *, filename, content: _async_value("图片中的文字：TaskMate OCR 测试"),
            ),
        )
        uploaded = await service.upload_base64_file(
            client_id="client_image",
            filename="note.png",
            content_type="image/png",
            content_base64=base64.b64encode(b"fake-image").decode(),
        )
        assert uploaded["chunk_count"] >= 1
        files = await repository.list_files(uploaded["user_id"])
        assert files[0].summary is not None
        assert "TaskMate OCR" in files[0].summary

    asyncio.run(run())


async def _async_value(value: str) -> str:
    return value
