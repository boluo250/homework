import asyncio
import json

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


class SlowChatProvider(ChatProviderBase):
    async def chat(self, *, system_prompt: str, user_message: str) -> str:
        await asyncio.sleep(0.02)
        return "# 永远不该看到这段"


class HangingChatProvider(ChatProviderBase):
    async def chat(self, *, system_prompt: str, user_message: str) -> str:
        await asyncio.Future()
        return "# 不会执行到这里"


class FakeQueueBinding:
    def __init__(self) -> None:
        self.messages: list[object] = []

    async def send(self, payload) -> None:
        self.messages.append(payload)


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
        assert job["research_profile"] == "technical_survey"
        assert job["research_profile_label"] == "技术调研"
        assert len(job["sub_runs"]) >= 4
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
        assert current["sub_runs"]
        assert all(item["status"] == "completed" for item in current["sub_runs"])

    asyncio.run(run())


def test_research_service_queue_mode_persists_state_and_completes() -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        queue = FakeQueueBinding()
        service = ResearchService(
            repository=repository,
            search_service=FakeSearchService(),
            web_fetch_service=FakeWebFetchService(),
            chat_provider=FakeChatProvider(),
            queue_binding=queue,
        )
        job = await service.submit(client_id="client_research_queue", query="Cloudflare Worker 上做 RAG 的轻量实现方案")
        assert job["status"] == "queued"
        assert queue.messages

        while queue.messages:
            message = queue.messages.pop(0)
            await service.process_queue_message(message)
            current = await service.get(job["id"])
            if current and current["status"] == "completed":
                break

        current = await service.get(job["id"])
        assert current is not None
        assert current["status"] == "completed"
        assert current["phase"] == "completed"
        assert current["current_step"] == current["total_steps"]
        assert len(current["events"]) >= 3
        assert all(item["status"] == "completed" for item in current["sub_runs"])

    asyncio.run(run())


def test_research_service_falls_back_when_synthesis_times_out() -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        service = ResearchService(
            repository=repository,
            search_service=FakeSearchService(),
            web_fetch_service=FakeWebFetchService(),
            chat_provider=SlowChatProvider(),
        )
        service.agent.SYNTHESIS_TIMEOUT_SECONDS = 0.001
        job = await service.submit(client_id="client_research_timeout", query="Cloudflare Worker 上做 RAG 的轻量实现方案")
        while True:
            current = await service.get(job["id"])
            if current and current["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0)
        assert current is not None
        assert current["status"] == "completed"
        report = current["report_markdown"] or ""
        assert "## 执行摘要" in report
        assert "## 推荐方案" in report
        assert "永远不该看到这段" not in report

    asyncio.run(run())


def test_research_service_get_resumes_stalled_queue_job_without_consumer() -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        queue = FakeQueueBinding()
        service = ResearchService(
            repository=repository,
            search_service=FakeSearchService(),
            web_fetch_service=FakeWebFetchService(),
            chat_provider=FakeChatProvider(),
            queue_binding=queue,
            stalled_job_timeout_seconds=0,
        )
        job = await service.submit(client_id="client_research_resume", query="Cloudflare Worker 上做 RAG 的轻量实现方案")
        assert job["status"] == "queued"
        assert queue.messages

        current = await service.get(job["id"], drive_stalled=True)
        while current and current["status"] not in {"completed", "failed"}:
            current = await service.get(job["id"], drive_stalled=True)

        assert current is not None
        assert current["status"] == "completed"
        assert current["phase"] == "completed"
        assert current["current_step"] == current["total_steps"]

    asyncio.run(run())


def test_research_service_get_finishes_stalled_synthesizing_job_with_fallback() -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        service = ResearchService(
            repository=repository,
            search_service=FakeSearchService(),
            web_fetch_service=FakeWebFetchService(),
            chat_provider=HangingChatProvider(),
            synthesis_stall_timeout_seconds=0,
        )
        user = await repository.get_or_create_user("client_research_stalled_synthesis")
        job = await repository.create_research_job(user.id, "Cloudflare Worker 上做 RAG 的轻量实现方案")
        plan = service.agent.build_plan(job.query)
        findings = [
            {
                "step": {
                    "title": plan[0].title,
                    "objective": plan[0].objective,
                    "search_queries": plan[0].search_queries,
                },
                "sources": [
                    {
                        "title": "Example result",
                        "url": "https://example.com/a",
                        "snippet": "关于实现路径和约束的摘要。",
                        "excerpt": "正文内容，包含 Cloudflare Worker、RAG 和 tradeoff 分析。",
                        "domain": "example.com",
                        "search_query": plan[0].search_queries[0],
                    }
                ],
                "findings": ["- Example result（example.com）：Cloudflare Worker 适合轻量 RAG 闭环。"],
            }
        ]
        references = [{"title": "Example result", "url": "https://example.com/a"}]
        await repository.update_research_job(job.id, status="running", report_markdown="正在汇总")
        await repository.create_research_job_state(
            job.id,
            phase="synthesizing",
            current_step=len(plan),
            total_steps=len(plan),
            plan_json=json.dumps(
                [
                    {
                        "title": item.title,
                        "objective": item.objective,
                        "search_queries": item.search_queries,
                    }
                    for item in plan
                ],
                ensure_ascii=False,
            ),
            findings_json=json.dumps(findings, ensure_ascii=False),
            references_json=json.dumps(references, ensure_ascii=False),
            started_at="2026-04-22T10:00:00+00:00",
        )

        current = await service.get(job.id)
        assert current is not None
        assert current["status"] == "completed"
        assert current["phase"] == "completed"
        report = current["report_markdown"] or ""
        assert "已自动切换为本地汇总结果" in report
        assert "## 执行摘要" in report
        assert "## 参考来源" in report

    asyncio.run(run())


def test_research_service_classifies_current_events_queries() -> None:
    async def run() -> None:
        repository = InMemoryAppRepository()
        service = ResearchService(
            repository=repository,
            search_service=FakeSearchService(),
            web_fetch_service=FakeWebFetchService(),
            chat_provider=FakeChatProvider(),
        )
        job = await service.submit(client_id="client_research_sports", query="调研梅西最近比赛动态和赛果")
        assert job["research_profile"] == "current_events"
        assert job["research_profile_label"] == "时效动态"
        titles = [item["title"] for item in job["sub_runs"]]
        assert any("时间线" in title or "最近" in title for title in titles)

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
