import asyncio
import base64

from app.core.agent import AssistantAgent
from app.core.models import ChatRequest
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.llm_base import ChatProviderBase, ToolCall, ToolChatResponse
from app.services.d1_repo import InMemoryAppRepository
from app.services.file_parser import FileParser
from app.services.file_service import FileService
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore
from app.services.rag_service import RagService
from app.services.search_service import SearchService
from app.state.file_state import FileState
from app.tools.rag_tool import RagTool


class FakeToolCallingProvider(ChatProviderBase):
    def supports_tool_calls(self) -> bool:
        return True

    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        _ = system_prompt
        _ = user_message
        return "普通聊天回复"

    async def chat_with_tools(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools,
    ) -> ToolChatResponse:
        _ = system_prompt
        _ = tools
        if "我叫小李" in user_message and "面试作业" in user_message:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="save_profile",
                        arguments={"name": "小李", "email": "xiaoli@example.com"},
                    ),
                    ToolCall(
                        name="create_task",
                        arguments={"title": "面试作业", "start_at": "2026-04-24", "end_at": "2026-04-30"},
                    ),
                ]
            )
        if "我叫小李" in user_message and "xiaoli@example.com" in user_message:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="save_profile",
                        arguments={"name": "小李", "email": "xiaoli@example.com"},
                    )
                ]
            )
        if "你知道我叫啥么" in user_message:
            return ToolChatResponse(
                tool_calls=[ToolCall(name="recall_profile", arguments={"field": "name"})]
            )
        if "修改任务" in user_message and "面试作业" in user_message:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="update_task",
                        arguments={
                            "title": "面试作业",
                            "new_title": "面试作业终版",
                            "details": "突出 Agent、RAG、Cloudflare Worker、D1 项目经验",
                            "status": "in_progress",
                            "priority": "high",
                            "start_at": "2026-04-25",
                            "end_at": "2026-05-01",
                        },
                    )
                ]
            )
        if "帮我创建个任务" in user_message:
            return ToolChatResponse(
                tool_calls=[ToolCall(name="create_task", arguments={"title": "个"})]
            )
        if "查询数据库里有哪些文档" in user_message:
            return ToolChatResponse(tool_calls=[ToolCall(name="list_uploaded_files", arguments={})])
        return ToolChatResponse(content="普通聊天回复")


class StickyDateToolCallingProvider(ChatProviderBase):
    def supports_tool_calls(self) -> bool:
        return True

    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        _ = system_prompt
        _ = user_message
        return "普通聊天回复"

    async def chat_with_tools(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools,
    ) -> ToolChatResponse:
        _ = system_prompt
        _ = tools
        if "我叫菠萝" in user_message:
            return ToolChatResponse(
                tool_calls=[ToolCall(name="save_profile", arguments={"name": "菠萝", "email": "bolo@example.com"})]
            )
        if "周报" in user_message and "2026-04-20" in user_message:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="create_task",
                        arguments={"title": "周报", "start_at": "2026-04-20", "end_at": "2026-04-21"},
                    )
                ]
            )
        if "帮我创建个任务" in user_message:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="create_task",
                        arguments={"title": "个", "end_at": "下周一"},
                    )
                ]
            )
        if "给二蛋发邮件" in user_message:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="create_task",
                        arguments={"title": "提醒：给二蛋发邮件", "start_at": "2026-03-22", "end_at": "2026-04-25"},
                    )
                ]
            )
        if "2026.3.22" in user_message:
            return ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        name="create_task",
                        arguments={"title": "提醒：给二蛋发邮件", "start_at": "2026-03-22", "end_at": "2026-04-25"},
                    )
                ]
            )
        return ToolChatResponse(content="普通聊天回复")


def test_tool_routing_can_save_profile_then_create_task(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=FakeToolCallingProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )

        created = await agent.handle_chat(
            ChatRequest(
                client_id="client_tool_route",
                message='我叫小李，邮箱 xiaoli@example.com，帮我创建一个"面试作业"任务，开始日期 2026-04-24，结束日期 2026-04-30',
            )
        )
        assert created.user_profile is not None
        assert created.user_profile.name == "小李"
        assert created.user_profile.email == "xiaoli@example.com"
        assert "已创建你的待办：面试作业" in created.reply

        user = await repository.get_or_create_user("client_tool_route")
        tasks = await repository.list_tasks(user.id)
        assert len(tasks) == 1
        assert tasks[0].title == "面试作业"
        assert tasks[0].start_at == "2026-04-24"
        assert tasks[0].end_at == "2026-04-30"

        recalled = await agent.handle_chat(
            ChatRequest(
                client_id="client_tool_route",
                conversation_id=created.conversation_id,
                message="你知道我叫啥么？",
            )
        )
        assert recalled.reply == "我记得你叫 小李。"

    asyncio.run(run())


def test_tool_routing_can_update_full_task_via_model(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=FakeToolCallingProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )

        created = await agent.handle_chat(
            ChatRequest(
                client_id="client_tool_update",
                message='我叫小李，邮箱 xiaoli@example.com，帮我创建一个"面试作业"任务，开始日期 2026-04-24，结束日期 2026-04-30',
            )
        )
        updated = await agent.handle_chat(
            ChatRequest(
                client_id="client_tool_update",
                conversation_id=created.conversation_id,
                message='请修改任务“面试作业”：标题改成“面试作业终版”，优先级改高，状态改成进行中，开始日期改成 2026-04-25，结束日期改成 2026-05-01，需求补充 D1 项目经验',
            )
        )

        user = await repository.get_or_create_user("client_tool_update")
        tasks = await repository.list_tasks(user.id)

        assert "任务已更新：面试作业终版" in updated.reply
        assert len(tasks) == 1
        assert tasks[0].title == "面试作业终版"
        assert tasks[0].status.value == "in_progress"
        assert tasks[0].priority.value == "high"
        assert tasks[0].start_at == "2026-04-25"
        assert tasks[0].end_at == "2026-05-01"
        assert "D1" in tasks[0].details

    asyncio.run(run())


def test_tool_routing_list_uploaded_files(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        qdrant = QdrantStore(storage_path=tmp_path / "vectors.json")
        file_service = FileService(
            repository=repository,
            file_store=R2FileStore(tmp_path / "r2"),
            file_parser=FileParser(),
            embedding_provider=RemoteEmbeddingProvider(),
            qdrant_store=qdrant,
        )
        file_state = FileState(repository)
        rag_tool = RagTool(
            file_state=file_state,
            file_service=file_service,
            rag_service=RagService(embedding_provider=RemoteEmbeddingProvider(), qdrant_store=qdrant),
            chat_provider=FakeToolCallingProvider(),
        )
        await file_service.upload_base64_file(
            client_id="client_list_files",
            filename="notes.txt",
            content_type="text/plain",
            content_base64=base64.b64encode(b"hello rag").decode("utf-8"),
        )
        agent = AssistantAgent(
            repository=repository,
            chat_provider=FakeToolCallingProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=qdrant,
            ),
            rag_tool=rag_tool,
        )
        await agent.handle_chat(
            ChatRequest(client_id="client_list_files", message="我叫小李，邮箱 xiaoli@example.com")
        )
        response = await agent.handle_chat(
            ChatRequest(client_id="client_list_files", message="查询数据库里有哪些文档")
        )
        assert "notes.txt" in response.reply
        assert any(tr.name == "list_uploaded_files" and tr.ok for tr in response.tool_results)

    asyncio.run(run())


def test_tool_routing_still_blocks_generic_task_title(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=FakeToolCallingProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )

        await agent.handle_chat(
            ChatRequest(
                client_id="client_tool_generic",
                message="我叫小李，邮箱 xiaoli@example.com",
            )
        )
        response = await agent.handle_chat(
            ChatRequest(
                client_id="client_tool_generic",
                message="帮我创建个任务",
            )
        )

        user = await repository.get_or_create_user("client_tool_generic")
        tasks = await repository.list_tasks(user.id)
        assert "这个任务想叫什么" in response.reply
        assert not tasks

    asyncio.run(run())


def test_tool_routing_does_not_reuse_old_dates_from_context(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=StickyDateToolCallingProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )

        profile = await agent.handle_chat(
            ChatRequest(client_id="client_sticky_dates", message="我叫菠萝，我的邮箱是 bolo@example.com")
        )
        await agent.handle_chat(
            ChatRequest(
                client_id="client_sticky_dates",
                conversation_id=profile.conversation_id,
                message='帮我创建一个"周报"任务，开始日期 2026-04-20，结束日期 2026-04-21',
            )
        )
        asked_title = await agent.handle_chat(
                ChatRequest(
                    client_id="client_sticky_dates",
                    conversation_id=profile.conversation_id,
                    message="帮我创建个任务，下周一前完成",
                )
            )
        answered_title = await agent.handle_chat(
            ChatRequest(
                client_id="client_sticky_dates",
                conversation_id=profile.conversation_id,
                message="给二蛋发邮件",
            )
        )

        user = await repository.get_or_create_user("client_sticky_dates")
        tasks = await repository.list_tasks(user.id)

        assert "这个任务想叫什么" in asked_title.reply
        assert answered_title.reply.endswith("开始日期是什么？")
        assert len(tasks) == 1
        assert tasks[0].title == "周报"

    asyncio.run(run())


def test_tool_routing_accepts_dotted_dates_for_pending_task(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=StickyDateToolCallingProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )

        profile = await agent.handle_chat(
            ChatRequest(client_id="client_dotted_dates", message="我叫菠萝，我的邮箱是 bolo@example.com")
        )
        await agent.handle_chat(
            ChatRequest(
                client_id="client_dotted_dates",
                conversation_id=profile.conversation_id,
                message="帮我创建个任务，优先级高",
            )
        )
        pending = await repository.get_pending_task_draft(profile.conversation_id)
        assert pending is not None
        assert pending.priority == "high"
        assert pending.missing_fields == ["title", "start_at", "end_at"]
        await agent.handle_chat(
            ChatRequest(
                client_id="client_dotted_dates",
                conversation_id=profile.conversation_id,
                message="给二蛋发邮件",
            )
        )
        created = await agent.handle_chat(
            ChatRequest(
                client_id="client_dotted_dates",
                conversation_id=profile.conversation_id,
                message="开始日期,2026.3.22 结束日期 2026.4.25",
            )
        )

        user = await repository.get_or_create_user("client_dotted_dates")
        tasks = await repository.list_tasks(user.id)

        assert "已创建你的待办：给二蛋发邮件" in created.reply
        assert len(tasks) == 1
        assert tasks[0].title == "给二蛋发邮件"
        assert tasks[0].start_at == "2026-03-22"
        assert tasks[0].end_at == "2026-04-25"
        assert await repository.get_pending_task_draft(profile.conversation_id) is None

    asyncio.run(run())
