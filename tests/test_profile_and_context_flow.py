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


def test_agent_accepts_call_me_phrase_and_uses_name_in_followup_reply(tmp_path) -> None:
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
            ChatRequest(client_id="client_profile_call_me", message="xiaoli@example.com")
        )
        second = await agent.handle_chat(
            ChatRequest(
                client_id="client_profile_call_me",
                conversation_id=first.conversation_id,
                message="你可以叫我小李",
            )
        )
        third = await agent.handle_chat(
            ChatRequest(
                client_id="client_profile_call_me",
                conversation_id=first.conversation_id,
                message='帮我创建一个"面试作业"任务',
            )
        )
        assert second.user_profile is not None
        assert second.user_profile.name == "小李"
        assert third.reply.startswith("小李，已创建任务")

    asyncio.run(run())


def test_agent_updates_assistant_name_from_nickname_phrase(tmp_path) -> None:
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
        profile = await agent.handle_chat(
            ChatRequest(client_id="client_bot_nickname_phrase", message="我叫小李，我的邮箱是 xiaoli@example.com")
        )
        renamed = await agent.handle_chat(
            ChatRequest(
                client_id="client_bot_nickname_phrase",
                conversation_id=profile.conversation_id,
                message="把你的昵称改成阿塔",
            )
        )
        assert renamed.assistant_name == "阿塔"
        settings = await repository.get_or_create_assistant_settings(profile.user_profile.id)
        assert settings.bot_name == "阿塔"

    asyncio.run(run())


def test_agent_does_not_create_task_with_generic_title(tmp_path) -> None:
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
        profile = await agent.handle_chat(
            ChatRequest(client_id="client_generic_title", message="我叫菠萝，我的邮箱是 bolo@example.com")
        )
        response = await agent.handle_chat(
            ChatRequest(
                client_id="client_generic_title",
                conversation_id=profile.conversation_id,
                message="帮我创建个任务",
            )
        )
        user = await repository.get_or_create_user("client_generic_title")
        tasks = await repository.list_tasks(user.id)
        assert "这个任务想叫什么" in response.reply
        assert not tasks

    asyncio.run(run())


def test_agent_answers_profile_query_without_overwriting_name(tmp_path) -> None:
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
        profile = await agent.handle_chat(
            ChatRequest(client_id="client_profile_query", message="我叫菠萝，我的邮箱是 bolo@example.com")
        )
        asked = await agent.handle_chat(
            ChatRequest(
                client_id="client_profile_query",
                conversation_id=profile.conversation_id,
                message="你知道我叫啥么？",
            )
        )
        current = await repository.get_or_create_user("client_profile_query")
        assert current.name == "菠萝"
        assert "菠萝" in asked.reply

    asyncio.run(run())


def test_agent_can_delete_recent_task_by_generic_reference(tmp_path) -> None:
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
        profile = await agent.handle_chat(
            ChatRequest(client_id="client_delete_recent", message="我叫菠萝，我的邮箱是 bolo@example.com")
        )
        await agent.handle_chat(
            ChatRequest(
                client_id="client_delete_recent",
                conversation_id=profile.conversation_id,
                message='帮我创建一个"任务一"任务',
            )
        )
        await agent.handle_chat(
            ChatRequest(
                client_id="client_delete_recent",
                conversation_id=profile.conversation_id,
                message='帮我创建一个"任务二"任务',
            )
        )
        deleted = await agent.handle_chat(
            ChatRequest(
                client_id="client_delete_recent",
                conversation_id=profile.conversation_id,
                message="删除已经创建的任务",
            )
        )
        user = await repository.get_or_create_user("client_delete_recent")
        tasks = await repository.list_tasks(user.id)
        titles = [task.title for task in tasks]
        assert "已删除任务：任务二" in deleted.reply
        assert titles == ["任务一"]

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
