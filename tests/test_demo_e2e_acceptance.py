import asyncio
import base64
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.agent import AssistantAgent
from app.core.http import HttpRequest, HttpResponse
from app.entry import route_request
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.llm_base import ChatProviderBase
from app.services.d1_repo import InMemoryAppRepository
from app.services.file_parser import FileParser
from app.services.file_service import FileService
from app.services.memory_service import MemoryService
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore
from app.services.rag_service import RagService
from app.services.research_service import ResearchService


class DemoSearchService:
    async def search(self, query: str, limit: int | None = None) -> list[dict]:
        _ = limit
        return [
            {
                "title": f"{query} - 官方概览",
                "url": "https://example.com/official",
                "snippet": "整理 Cloudflare Worker、RAG、文件处理和任务管理的实现要点。",
            },
            {
                "title": f"{query} - 工程实践",
                "url": "https://example.com/engineering",
                "snippet": "总结轻量架构、成本控制和面试演示重点。",
            },
        ]


class DemoWebFetchService:
    async def fetch_text(self, url: str) -> str:
        return (
            f"{url} 的正文提到：Cloudflare Worker 适合做轻量 Agent 编排，"
            "D1 负责结构化数据，R2 负责文件，Qdrant 负责向量检索，"
            "研究模式可以拆成多个子问题后再汇总成报告。"
        )


class DemoAgentChatProvider(ChatProviderBase):
    async def chat(self, *, system_prompt: str, user_message: str) -> str:
        if "file question-answering assistant" in system_prompt:
            return (
                "这份资料主要围绕 Agent、RAG、Cloudflare Worker 交付经验展开，适合用来支撑简历和项目说明。\n"
                "EVIDENCE_IDS: [1]"
            )
        return "这是一个本地演示回答，用于验证端到端链路。"


class DemoResearchChatProvider(ChatProviderBase):
    async def chat(self, *, system_prompt: str, user_message: str) -> str:
        return (
            "# 研究报告\n\n"
            "## 执行摘要\n\n"
            "建议采用 Cloudflare Worker + D1 + R2 + Qdrant 的轻量闭环，优先保证作业演示稳定性。\n\n"
            "## 子代理规划\n\n"
            "- 子代理 1：明确问题边界与目标\n"
            "- 子代理 2：收集候选实现方案\n"
            "- 子代理 3：验证运行时约束与成本\n"
            "- 子代理 4：汇总推荐方案与实施顺序\n\n"
            "## 关键发现\n\n"
            "- Worker 足够承载聊天、任务 CRUD、文件上传和轻量检索。\n"
            "- 深度研究更适合拆成多个步骤执行，再统一生成结构化报告。\n"
            "- RAG 检索必须按 user_id 和 file_id 做过滤，避免串数据。\n\n"
            "## 推荐方案\n\n"
            "- 先做稳定的对话 + 任务 + 文件 + 研究闭环，再增强多模态与更复杂的推理模式。\n\n"
            "## 参考来源\n\n"
            "- [Official](https://example.com/official)\n"
            "- [Engineering](https://example.com/engineering)\n"
        )


@dataclass
class DemoContainer:
    repository: InMemoryAppRepository
    agent: AssistantAgent
    file_service: FileService
    research_service: ResearchService


def test_demo_e2e_chat_task_and_search_flow(tmp_path: Path) -> None:
    async def run() -> None:
        container = build_demo_container(tmp_path)
        client_id = "demo-chat-task-client"

        home = await request(container, "GET", "/")
        assert home.status == 200
        assert "TaskMate Worker Demo" in home.body.decode("utf-8")

        blocked = await chat(container, client_id, '帮我创建一个"面试作业"任务，要求突出 Agent 和 RAG 能力')
        assert blocked["intent"] == "task_crud"
        assert "名字和邮箱" in blocked["reply"]

        task_list = await request_json(container, "GET", f"/api/tasks?client_id={client_id}")
        assert task_list["tasks"] == []

        profile = await chat(
            container,
            client_id,
            "我叫小李，我的邮箱是 xiaoli@example.com，叫你阿塔",
            conversation_id=blocked["conversation_id"],
        )
        assert "我记住了" in profile["reply"]
        assert profile["assistant_name"] == "阿塔"

        session_meta = await request_json(container, "GET", f"/api/chat?client_id={client_id}")
        assert session_meta["user_profile"]["name"] == "小李"
        assert session_meta["user_profile"]["email"] == "xiaoli@example.com"
        assert session_meta["assistant_name"] == "阿塔"

        created = await chat(
            container,
            client_id,
            '帮我创建一个"面试作业"任务，要求突出 Agent、RAG、Cloudflare Worker 项目经验，开始日期 2026-04-24，结束日期 2026-04-30，高优先级',
            conversation_id=profile["conversation_id"],
        )
        assert "已创建你的待办" in created["reply"]
        assert "需求" in created["reply"]

        tasks_before_patch = await request_json(container, "GET", f"/api/tasks?client_id={client_id}")
        [created_task] = tasks_before_patch["tasks"]
        patched = await request_json(
            container,
            "PATCH",
            "/api/tasks",
            {
                "client_id": client_id,
                "task_id": created_task["id"],
                "title": "面试作业-终版",
                "details": "突出 Agent、RAG、Cloudflare Worker、D1 项目经验",
                "status": "in_progress",
                "priority": "medium",
                "start_at": "2026-04-25",
                "end_at": "2026-05-01",
            },
        )
        assert patched["task"]["title"] == "面试作业-终版"
        assert patched["task"]["status"] == "in_progress"
        assert patched["task"]["priority"] == "medium"
        assert patched["task"]["start_at"] == "2026-04-25"
        assert patched["task"]["end_at"] == "2026-05-01"

        listed = await chat(container, client_id, "列出我的任务", conversation_id=profile["conversation_id"])
        assert "面试作业-终版" in listed["reply"]
        assert "Cloudflare Worker、D1" in listed["reply"]

        task_detail = await chat(
            container,
            client_id,
            '看看"面试作业"任务的具体需求',
            conversation_id=profile["conversation_id"],
        )
        assert "待办详情" in task_detail["reply"]
        assert "Cloudflare Worker、D1 项目经验" in task_detail["reply"]

        search_result = await chat(
            container,
            client_id,
            "请联网搜索一下 Cloudflare Worker 最新 AI 能力",
            conversation_id=profile["conversation_id"],
        )
        assert search_result["intent"] == "search_web"
        assert search_result["tool_results"][0]["name"] == "search_web"
        assert "我先帮你整理了搜索结果" in search_result["reply"]

    asyncio.run(run())


def test_demo_e2e_file_workspace_and_rag_flow(tmp_path: Path) -> None:
    async def run() -> None:
        container = build_demo_container(tmp_path)
        client_id = "demo-file-client"

        profile = await chat(container, client_id, "我叫王同学，我的邮箱是 wang@example.com")
        assert profile["user_profile"]["name"] == "王同学"

        upload = await request_json(
            container,
            "POST",
            "/api/files",
            {
                "client_id": client_id,
                "filename": "resume.md",
                "content_type": "text/markdown",
                "content_base64": base64.b64encode(
                    (
                        "# 项目经历\n"
                        "- 负责 Agent 平台设计\n"
                        "- 落地 RAG、文档解析、向量检索\n"
                        "- 使用 Cloudflare Worker + D1 + Qdrant 交付演示系统\n"
                    ).encode("utf-8")
                ).decode("utf-8"),
            },
        )
        assert upload["chunk_count"] >= 1
        assert upload["vector_count"] >= 1
        file_id = upload["file"]["id"]

        file_list = await request_json(container, "GET", f"/api/files?client_id={client_id}")
        assert len(file_list["files"]) == 1
        assert file_list["files"][0]["filename"] == "resume.md"
        assert file_list["files"][0]["vector_count"] >= 1

        file_detail = await request_json(
            container,
            "GET",
            f"/api/files?client_id={client_id}&file_id={file_id}",
        )
        assert file_detail["file"]["filename"] == "resume.md"
        assert file_detail["vector_count"] >= 1
        assert "Cloudflare Worker" in file_detail["preview_text"]

        renamed = await request_json(
            container,
            "PATCH",
            "/api/files",
            {
                "client_id": client_id,
                "file_id": file_id,
                "filename": "resume-final.md",
            },
        )
        assert renamed["file"]["filename"] == "resume-final.md"

        renamed_detail = await request_json(
            container,
            "GET",
            f"/api/files?client_id={client_id}&file_id={file_id}",
        )
        assert renamed_detail["file"]["filename"] == "resume-final.md"
        assert "Agent 平台设计" in renamed_detail["preview_text"]

        answer = await chat(
            container,
            client_id,
            "总结这个文档的核心内容",
            file_ids=[file_id],
            conversation_id=profile["conversation_id"],
        )
        assert answer["intent"] == "file_qa"
        assert "Agent、RAG、Cloudflare Worker" in answer["reply"]
        assert "参考来源" in answer["reply"]
        assert "resume-final.md#片段0" in answer["reply"]

        deleted = await request_json(
            container,
            "DELETE",
            f"/api/files?client_id={client_id}&file_id={file_id}",
        )
        assert deleted["deleted"]["id"] == file_id

        empty_list = await request_json(container, "GET", f"/api/files?client_id={client_id}")
        assert empty_list["files"] == []

        no_recall = await chat(
            container,
            client_id,
            "继续总结这个文档",
            file_ids=[file_id],
            conversation_id=profile["conversation_id"],
        )
        assert "当前还没有可用的向量检索结果" in no_recall["reply"]

    asyncio.run(run())


def test_demo_e2e_research_submit_and_poll(tmp_path: Path) -> None:
    async def run() -> None:
        container = build_demo_container(tmp_path)
        client_id = "demo-research-client"

        created = await request_json(
            container,
            "POST",
            "/api/research",
            {
                "client_id": client_id,
                "query": "帮我调研 Cloudflare Worker 上实现任务管理助手 + RAG 的轻量方案",
            },
        )
        job_id = created["id"]
        assert created["status"] in {"queued", "running"}

        current = created
        for _ in range(40):
            if current["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0)
            current = await request_json(container, "GET", f"/api/research?job_id={job_id}")

        assert current["status"] == "completed"
        assert current["phase"] == "completed"
        assert current["current_step"] == current["total_steps"]
        report = current["report_markdown"] or ""
        assert "## 执行摘要" in report
        assert "## 子代理规划" in report
        assert "## 关键发现" in report
        assert "## 推荐方案" in report
        assert "## 参考来源" in report

    asyncio.run(run())


def test_demo_e2e_new_session_keeps_profile_but_rotates_conversation(tmp_path: Path) -> None:
    async def run() -> None:
        container = build_demo_container(tmp_path)
        client_id = "demo-session-client"

        first = await chat(container, client_id, "我叫小周，我的邮箱是 zhou@example.com，叫你阿周")
        first_conversation_id = first["conversation_id"]
        assert first["user_profile"]["name"] == "小周"
        assert first["assistant_name"] == "阿周"

        second = await chat(container, client_id, "列出我的任务")
        second_conversation_id = second["conversation_id"]
        assert second_conversation_id != first_conversation_id
        assert "名字和邮箱" not in second["reply"]

        session_meta = await request_json(container, "GET", f"/api/chat?client_id={client_id}")
        assert session_meta["user_profile"]["name"] == "小周"
        assert session_meta["user_profile"]["email"] == "zhou@example.com"
        assert session_meta["assistant_name"] == "阿周"

    asyncio.run(run())


def test_demo_e2e_admin_reset_clears_workspace_data(tmp_path: Path) -> None:
    async def run() -> None:
        container = build_demo_container(tmp_path)
        client_id = "demo-reset-client"

        profile = await chat(container, client_id, "我叫小陈，我的邮箱是 chen@example.com")
        await chat(
            container,
            client_id,
            '帮我创建一个"清空测试"任务，要求验证 reset 接口，开始日期 2026-04-24，结束日期 2026-04-25',
            conversation_id=profile["conversation_id"],
        )
        await request_json(
            container,
            "POST",
            "/api/files",
            {
                "client_id": client_id,
                "filename": "reset-note.md",
                "content_type": "text/markdown",
                "content_base64": base64.b64encode("# reset\n验证清空能力".encode("utf-8")).decode("utf-8"),
            },
        )

        reset_payload = await request_json(
            container,
            "POST",
            "/api/admin/reset",
            {"confirm": "RESET_ALL_DATA"},
        )
        assert reset_payload["ok"] is True

        tasks = await request_json(container, "GET", f"/api/tasks?client_id={client_id}")
        files = await request_json(container, "GET", f"/api/files?client_id={client_id}")
        session_meta = await request_json(container, "GET", f"/api/chat?client_id={client_id}")
        assert tasks["tasks"] == []
        assert files["files"] == []
        assert session_meta["user_profile"]["name"] in {None, ""}
        assert session_meta["user_profile"]["email"] in {None, ""}

    asyncio.run(run())


def build_demo_container(tmp_path: Path) -> DemoContainer:
    repository = InMemoryAppRepository()
    qdrant_store = QdrantStore(storage_path=tmp_path / "vectors.json")
    embedding_provider = RemoteEmbeddingProvider()
    agent = AssistantAgent(
        repository=repository,
        chat_provider=DemoAgentChatProvider(),
        search_service=DemoSearchService(),
        rag_service=RagService(
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
        ),
        memory_service=MemoryService(
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
        ),
    )
    file_service = FileService(
        repository=repository,
        file_store=R2FileStore(tmp_path / "r2"),
        file_parser=FileParser(),
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
    )
    research_service = ResearchService(
        repository=repository,
        search_service=DemoSearchService(),
        web_fetch_service=DemoWebFetchService(),
        chat_provider=DemoResearchChatProvider(),
    )
    return DemoContainer(
        repository=repository,
        agent=agent,
        file_service=file_service,
        research_service=research_service,
    )


async def chat(
    container: DemoContainer,
    client_id: str,
    message: str,
    *,
    conversation_id: str | None = None,
    file_ids: list[str] | None = None,
) -> dict:
    payload = {"client_id": client_id, "message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if file_ids:
        payload["file_ids"] = file_ids
    return await request_json(container, "POST", "/api/chat", payload)


async def request_json(
    container: DemoContainer,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    response = await request(container, method, path, payload)
    assert response.headers.get("content-type", "").startswith("application/json")
    return json.loads(response.body.decode("utf-8"))


async def request(
    container: DemoContainer,
    method: str,
    path: str,
    payload: dict | None = None,
) -> HttpResponse:
    body = b""
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    request_obj = HttpRequest.from_raw(
        method=method,
        url=f"https://demo.local{path}",
        headers=headers,
        body=body,
    )
    return await route_request(request_obj, container)
