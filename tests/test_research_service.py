import asyncio

from app.core.agent import AssistantAgent
from app.core.models import ChatRequest
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.llm_base import ChatProviderBase
from app.providers.openrouter_chat import OpenRouterChatProvider
from app.services.d1_repo import InMemoryAppRepository
from app.services.qdrant_store import QdrantStore
from app.services.rag_service import RagService
from app.services.research_service import ResearchService


class FakeSearchService:
    async def search(self, query: str) -> list[dict]:
        return [
            {
                "title": f"{query} result A",
                "url": "https://example.com/a",
                "snippet": "关于实现路径和约束的摘要。",
            },
            {
                "title": f"{query} result B",
                "url": "https://example.com/b",
                "snippet": "关于成本与风险的摘要。",
            },
        ]


class FakeWebFetchService:
    async def fetch_text(self, url: str) -> str:
        return f"{url} 正文内容，包含 Cloudflare Worker、RAG 和 tradeoff 分析。"


class FakeChatProvider(ChatProviderBase):
    async def chat(self, *, system_prompt: str, user_message: str) -> str:
        return (
            "# 研究报告\n\n"
            "## 执行摘要\n\n"
            "建议把研究链路拆成独立 research agent，执行搜索、抓取与汇总。\n\n"
            "## 研究拆解\n\n"
            "- 拆题\n- 搜索\n- 阅读\n- 汇总\n\n"
            "## 关键发现\n\n"
            "- Cloudflare Worker 适合轻量 RAG 闭环。\n\n"
            "## 方案对比\n\n"
            "- 轻量路径更适合当前作业。\n\n"
            "## 推荐方案\n\n"
            "- 先做稳定闭环，再增强多代理。\n\n"
            "## 风险与未决问题\n\n"
            "- 搜索和抓取依赖外部 API。\n\n"
            "## 参考来源\n\n"
            "- [Example](https://example.com/a)\n"
        )


def test_research_service_generates_structured_report() -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        service = ResearchService(
            repository=repository,
            search_service=FakeSearchService(),
            web_fetch_service=FakeWebFetchService(),
            chat_provider=FakeChatProvider(),
        )
        job = await service.submit(client_id="client_research", query="Cloudflare Worker 上做 RAG 的轻量实现方案")
        while True:
            current = await service.get(job["id"])
            if current["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0)
        assert current["status"] == "completed"
        report = current["report_markdown"] or ""
        assert "## 研究拆解" in report
        assert "## 关键发现" in report
        assert "## 方案对比" in report
        assert "## 参考来源" in report

    asyncio.run(run())


def test_agent_deep_research_reply_announces_real_execution(tmp_path) -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        agent = AssistantAgent(
            repository=repository,
            chat_provider=OpenRouterChatProvider(),
            search_service=FakeSearchService(),
            rag_service=RagService(
                embedding_provider=RemoteEmbeddingProvider(),
                qdrant_store=QdrantStore(storage_path=tmp_path / "vectors.json"),
            ),
        )
        response = await agent.handle_chat(
            ChatRequest(
                client_id="client_research_chat",
                message="我叫小李，邮箱 xiaoli@example.com，帮我调研 Cloudflare Worker 做 RAG 的轻量方案",
            )
        )
        assert "开始真正执行这次研究" in response.reply
        assert any(item.name == "deep_research_job" for item in response.tool_results)

    asyncio.run(run())
