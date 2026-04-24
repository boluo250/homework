import asyncio
import base64

from app.core.agent import AssistantAgent
from app.core.models import ChatRequest
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.llm_base import ChatProviderBase, ToolChatResponse
from app.services.d1_repo import InMemoryAppRepository
from app.services.file_parser import FileParser
from app.services.file_service import FileService
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore
from app.services.rag_service import RagService
from app.services.search_service import SearchService
from app.state.file_state import FileState
from app.tools.rag_tool import RagTool


class FakeChatProvider(ChatProviderBase):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.system_prompt = ""
        self.user_message = ""

    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        self.calls.append((system_prompt, user_message))
        self.system_prompt = system_prompt
        self.user_message = user_message
        if "strict intent interpreter" in system_prompt:
            return """
            {
              "primary_intent": "file_qa",
              "task_action": null,
              "should_execute": true,
              "needs_clarification": false,
              "clarification_prompt": null,
              "confidence": 0.98,
              "target_ref": null,
              "task_title": null,
              "task_details": null,
              "task_priority": null,
              "task_due_at": null,
              "task_status": null,
              "user_name": null,
              "user_email": null,
              "assistant_name": null,
              "write_profile": false,
              "rename_assistant": false,
              "profile_query_field": null,
              "assistant_query": false,
              "explanation": "selected file question"
            }
            """
        return "这是一段归纳后的回答。\nEVIDENCE_IDS: [1]"


class NoEvidenceIdChatProvider(FakeChatProvider):
    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        if "strict intent interpreter" in system_prompt:
            return await super().chat(system_prompt=system_prompt, user_message=user_message)
        self.calls.append((system_prompt, user_message))
        self.system_prompt = system_prompt
        self.user_message = user_message
        return "这是一段归纳后的回答。"


class ToolRoutingBypassChatProvider(FakeChatProvider):
    def supports_tool_calls(self) -> bool:
        return True

    async def chat_with_tools(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools,
    ) -> ToolChatResponse:
        _ = system_prompt
        _ = user_message
        _ = tools
        return ToolChatResponse(content="这是工具路由直接返回的普通回答。")


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
        assert response.reply.startswith("这是一段归纳后的回答。")
        assert "参考来源" in response.reply
        assert response.reply.count("#片段") == 1
        assert "Retrieved evidence" in chat_provider.system_prompt
        assert "Full document context" in chat_provider.system_prompt
        assert "EVIDENCE_IDS: [ids]" in chat_provider.system_prompt
        assert "不要只摘抄原文" in chat_provider.user_message
        assert "整体概括" in chat_provider.user_message

    asyncio.run(run())


def test_file_inventory_lists_persisted_uploads_without_tool_calls(tmp_path) -> None:
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
        await file_service.upload_base64_file(
            client_id="client_inventory",
            filename="readme.md",
            content_type="text/markdown",
            content_base64=base64.b64encode(b"# Demo\nRAG inventory test.").decode("utf-8"),
        )
        rag_tool = RagTool(
            file_state=FileState(repository),
            file_service=file_service,
            rag_service=RagService(embedding_provider=RemoteEmbeddingProvider(), qdrant_store=qdrant),
            chat_provider=chat_provider,
        )
        agent = AssistantAgent(
            repository=repository,
            chat_provider=chat_provider,
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=qdrant,
            ),
            rag_tool=rag_tool,
        )
        response = await agent.handle_chat(
            ChatRequest(client_id="client_inventory", message="查询数据库里有哪些文档")
        )
        assert "readme.md" in response.reply
        assert any(tr.name == "list_uploaded_files" and tr.ok for tr in response.tool_results)

    asyncio.run(run())


def test_file_qa_uses_compare_prompt_bundle(tmp_path) -> None:
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
            client_id="client_compare",
            filename="compare.txt",
            content_type="text/plain",
            content_base64=base64.b64encode(
                (
                    "方案A\n成本低，适合 MVP。\n\n"
                    "方案B\n扩展性强，适合长期演进。"
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
                client_id="client_compare",
                message="对比一下这个文档里的方案A和方案B",
                file_ids=[uploaded["file"]["id"]],
            )
        )
        assert response.reply.startswith("这是一段归纳后的回答。")
        assert "Template: compare." in chat_provider.system_prompt
        assert "按维度比较相同点、不同点和适用场景" in chat_provider.user_message

    asyncio.run(run())


def test_file_qa_without_evidence_ids_does_not_append_blind_citations(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        chat_provider = NoEvidenceIdChatProvider()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        file_service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
        )
        uploaded = await file_service.upload_base64_file(
            client_id="client_no_ids",
            filename="notes.txt",
            content_type="text/plain",
            content_base64=base64.b64encode(b"alpha\nbeta\ngamma").decode("utf-8"),
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
                client_id="client_no_ids",
                message="总结一下这个文档",
                file_ids=[uploaded["file"]["id"]],
            )
        )
        assert response.reply == "这是一段归纳后的回答。"
        assert "参考来源" not in response.reply

    asyncio.run(run())


def test_selected_file_summary_bypasses_router_plain_text_reply(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        chat_provider = ToolRoutingBypassChatProvider()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        file_service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
        )
        uploaded = await file_service.upload_base64_file(
            client_id="client_force_file_qa",
            filename="agent-memory.txt",
            content_type="text/plain",
            content_base64=base64.b64encode(
                b"Agent memory keeps short-term and long-term knowledge for multi-turn tasks."
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
                client_id="client_force_file_qa",
                message="总结 agent-memory.docx",
                file_ids=[uploaded["file"]["id"]],
            )
        )
        assert response.intent.value == "file_qa"
        assert response.reply.startswith("这是一段归纳后的回答。")
        assert "工具路由直接返回的普通回答" not in response.reply

    asyncio.run(run())
