import asyncio

from app.core.agent import AssistantAgent
from app.core.models import ChatRequest
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.openrouter_chat import OpenRouterChatProvider
from app.services.d1_repo import InMemoryAppRepository
from app.services.qdrant_store import QdrantStore
from app.services.rag_service import RagService
from app.services.search_service import SearchService


def test_agent_task_flow_create_then_list(tmp_path) -> None:
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
        created = await agent.handle_chat(
            ChatRequest(client_id="client_test", message='帮我创建一个"项目复盘"任务，明天完成，高优先级')
        )
        listed = await agent.handle_chat(
            ChatRequest(
                client_id="client_test",
                message="列出我的任务",
                conversation_id=created.conversation_id,
            )
        )
        assert "开始之前" in created.reply
        completed_profile = await agent.handle_chat(
            ChatRequest(
                client_id="client_test",
                message="我叫小王，我的邮箱是 xiaowang@example.com",
                conversation_id=created.conversation_id,
            )
        )
        created_after_profile = await agent.handle_chat(
            ChatRequest(
                client_id="client_test",
                message='帮我创建一个"项目复盘"任务，要求补齐结论和行动项，明天完成，高优先级',
                conversation_id=completed_profile.conversation_id,
            )
        )
        listed_after_profile = await agent.handle_chat(
            ChatRequest(
                client_id="client_test",
                message="列出我的任务",
                conversation_id=completed_profile.conversation_id,
            )
        )
        detailed_after_profile = await agent.handle_chat(
            ChatRequest(
                client_id="client_test",
                message='看看"项目复盘"任务的具体需求',
                conversation_id=completed_profile.conversation_id,
            )
        )
        assert "已创建任务" in created_after_profile.reply
        assert "需求" in created_after_profile.reply
        assert "项目复盘" in listed_after_profile.reply
        assert "行动项" in listed_after_profile.reply
        assert "任务详情" in detailed_after_profile.reply
        assert "行动项" in detailed_after_profile.reply

    asyncio.run(run())
