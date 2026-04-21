import asyncio

from app.core.agent import AssistantAgent
from app.core.context import ConversationContextManager
from app.core.models import ChatRequest
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.openrouter_chat import OpenRouterChatProvider
from app.services.d1_repo import InMemoryAppRepository
from app.services.qdrant_store import QdrantStore
from app.services.rag_service import RagService
from app.services.search_service import SearchService


def test_agent_updates_profile_and_bot_name(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=OpenRouterChatProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )
        response = await agent.handle_chat(
            ChatRequest(client_id="client_profile", message="我叫小李，我的邮箱是 xiaoli@example.com，叫你阿塔")
        )
        assert response.user_profile is not None
        assert response.user_profile.name == "小李"
        assert response.user_profile.email == "xiaoli@example.com"
        assert response.assistant_name == "阿塔"
        settings = await repository.get_or_create_assistant_settings(response.user_profile.id)
        assert settings.bot_name == "阿塔"

    asyncio.run(run())


def test_agent_accepts_standalone_name_after_email_prompt(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=OpenRouterChatProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )
        first = await agent.handle_chat(
            ChatRequest(client_id="client_profile_name", message="xiaoli@example.com")
        )
        second = await agent.handle_chat(
            ChatRequest(
                client_id="client_profile_name",
                conversation_id=first.conversation_id,
                message="小李",
            )
        )
        assert second.user_profile is not None
        assert second.user_profile.email == "xiaoli@example.com"
        assert second.user_profile.name == "小李"
        assert "我记住了" in second.reply

    asyncio.run(run())


def test_agent_accepts_email_and_name_in_single_loose_message(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=OpenRouterChatProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )
        response = await agent.handle_chat(
            ChatRequest(client_id="client_profile_loose", message="169180920@qq.com 菠萝")
        )
        assert response.user_profile is not None
        assert response.user_profile.email == "169180920@qq.com"
        assert response.user_profile.name == "菠萝"

    asyncio.run(run())


def test_agent_returns_profile_saved_reply_when_completion_finishes_this_turn(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=OpenRouterChatProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )
        first = await agent.handle_chat(
            ChatRequest(client_id="client_profile_finish", message="169180920@qq.com")
        )
        second = await agent.handle_chat(
            ChatRequest(
                client_id="client_profile_finish",
                conversation_id=first.conversation_id,
                message="菠萝",
            )
        )
        assert second.user_profile is not None
        assert second.user_profile.name == "菠萝"
        assert second.user_profile.email == "169180920@qq.com"
        assert "好的，我记住了" in second.reply

    asyncio.run(run())


def test_agent_blocks_task_execution_until_profile_completed(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=OpenRouterChatProvider(),
            search_service=SearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )
        response = await agent.handle_chat(
            ChatRequest(client_id="client_profile_gate", message='帮我创建一个"简历优化"任务，要求突出 Agent 项目经历')
        )
        user = await repository.get_or_create_user("client_profile_gate")
        tasks = await repository.list_tasks(user.id)
        assert "名字和邮箱" in response.reply
        assert not tasks

    asyncio.run(run())


def test_context_manager_merges_summary_and_recent_messages() -> None:
    manager = ConversationContextManager(recent_limit=2, summary_trigger=3)
    repository = InMemoryAppRepository()

    async def run() -> None:
        user = await repository.get_or_create_user("client_ctx")
        conversation = await repository.get_or_create_conversation(user.id)
        for index in range(5):
            await repository.add_message(conversation.id, "user", f"message {index}")
        messages = await repository.list_messages(conversation.id, limit=10)
        bundle = manager.build(messages)
        assert bundle.summary_text is not None
        assert len(bundle.recent_lines) == 2

    asyncio.run(run())
