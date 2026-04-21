from __future__ import annotations

import asyncio

from app.providers.llm_base import ChatProviderBase
from app.services.d1_repo import AppRepository
from app.services.research_agent import ResearchAgent
from app.services.search_service import SearchService
from app.services.web_fetch_service import WebFetchService


class ResearchService:
    def __init__(
        self,
        repository: AppRepository,
        search_service: SearchService,
        web_fetch_service: WebFetchService,
        chat_provider: ChatProviderBase | None = None,
    ) -> None:
        self.repository = repository
        self.agent = ResearchAgent(
            search_service=search_service,
            web_fetch_service=web_fetch_service,
            chat_provider=chat_provider,
        )
        self.running_jobs: dict[str, asyncio.Task] = {}

    async def submit(self, *, client_id: str, query: str) -> dict:
        user = await self.repository.get_or_create_user(client_id)
        job = await self.repository.create_research_job(user.id, query)
        self.running_jobs[job.id] = asyncio.create_task(self._run_job(job.id, query))
        return job.to_dict()

    async def get(self, job_id: str) -> dict | None:
        job = await self.repository.get_research_job(job_id)
        return job.to_dict() if job else None

    async def _run_job(self, job_id: str, query: str) -> None:
        try:
            async def push_progress(status: str, markdown: str) -> None:
                await self.repository.update_research_job(
                    job_id,
                    status=status,
                    report_markdown=markdown,
                )

            final_report = await self.agent.execute(query=query, on_progress=push_progress)
            await self.repository.update_research_job(
                job_id,
                status="completed",
                report_markdown=final_report,
            )
        except Exception as exc:
            await self.repository.update_research_job(
                job_id,
                status="failed",
                report_markdown=f"# 研究失败\n\n- 状态：failed\n- 原因：{exc}",
            )
        finally:
            self.running_jobs.pop(job_id, None)
