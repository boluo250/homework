import asyncio

from app.core.agent import AssistantAgent
from app.core.models import ChatRequest
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.llm_base import ChatProviderBase, ToolCall, ToolChatResponse
from app.services.d1_repo import InMemoryAppRepository
from app.services.qdrant_store import QdrantStore
from app.services.rag_service import RagService
from app.services.search_service import SearchService


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
                        arguments={"title": "面试作业"},
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
        if "帮我创建个任务" in user_message:
            return ToolChatResponse(
                tool_calls=[ToolCall(name="create_task", arguments={"title": "个"})]
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
                message='我叫小李，邮箱 xiaoli@example.com，帮我创建一个"面试作业"任务',
            )
        )
        assert created.user_profile is not None
        assert created.user_profile.name == "小李"
        assert created.user_profile.email == "xiaoli@example.com"
        assert "已创建任务：面试作业" in created.reply

        user = await repository.get_or_create_user("client_tool_route")
        tasks = await repository.list_tasks(user.id)
        assert len(tasks) == 1
        assert tasks[0].title == "面试作业"

        recalled = await agent.handle_chat(
            ChatRequest(
                client_id="client_tool_route",
                conversation_id=created.conversation_id,
                message="你知道我叫啥么？",
            )
        )
        assert recalled.reply == "我记得你叫 小李。"

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
