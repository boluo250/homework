import asyncio
import base64

from app.core.agent import AssistantAgent
from app.core.models import ChatRequest
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.llm_base import ChatProviderBase
from app.services.d1_repo import InMemoryAppRepository
from app.services.file_parser import FileParser
from app.services.file_service import FileService
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore
from app.services.rag_service import RagService
from app.services.search_service import SearchService


class FakeChatProvider(ChatProviderBase):
    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_message = ""

    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        self.system_prompt = system_prompt
        self.user_message = user_message
        return "这是一段归纳后的回答。"


def test_file_qa_uses_llm_to_summarize_retrieved_context(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        chat_provider = FakeChatProvider()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        file_service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
        )
        uploaded = await file_service.upload_base64_file(
            client_id="client_resume",
            filename="resume.txt",
            content_type="text/plain",
            content_base64=base64.b64encode(
                (
                    "个人信息\n柯曦明，Agent Platform Architect\n\n"
                    "工作经历\n主导 Agent 平台、RAG、文档解析、搜索推荐系统。\n\n"
                    "技能\nPython、Cloudflare Workers、向量检索。"
                ).encode("utf-8")
            ).decode("utf-8"),
        )
        agent = AssistantAgent(
            repository=repository,
            chat_provider=chat_provider,
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=qdrant,
            ),
        )
        response = await agent.handle_chat(
            ChatRequest(
                client_id="client_resume",
                message="总结一下这个文档的核心内容",
                file_ids=[uploaded["file"]["id"]],
            )
        )
        assert response.reply == "这是一段归纳后的回答。"
        assert "Retrieved evidence" in chat_provider.system_prompt
        assert "Full document context" in chat_provider.system_prompt
        assert "不要只摘抄原文" in chat_provider.user_message
        assert "整体概括" in chat_provider.user_message

    asyncio.run(run())
