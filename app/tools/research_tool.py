from __future__ import annotations

import json

from app.state.research_state import ResearchState


class ResearchTool:
    def __init__(self, research_state: ResearchState | None, research_service=None) -> None:
        self.research_state = research_state
        self.research_service = research_service

    def build_plan(self, message: str) -> list[str]:
        return [
            f"明确研究目标：{message}",
            "拆分 3 到 5 个子问题并定义各自的证据来源",
            "对子问题执行搜索、阅读和摘要压缩",
            "汇总成结构化 Markdown 报告并给出推荐结论",
        ]

    async def create_job(self, *, client_id: str, query: str) -> dict:
        if self.research_service is None:
            raise RuntimeError("research service is not configured")
        return await self.research_service.submit(client_id=client_id, query=query)

    async def get_job(self, job_id: str) -> dict | None:
        if self.research_service is None:
            if self.research_state is None:
                return None
            job = await self.research_state.get_job(job_id)
            return job.to_dict() if job else None
        return await self.research_service.get(job_id, drive_stalled=True)

    async def list_jobs(self, user_id: str) -> list[dict]:
        if self.research_state is None:
            return []
        return [job.to_dict() for job in await self.research_state.list_jobs(user_id)]

    async def update_phase(
        self,
        job_id: str,
        *,
        phase: str,
        current_step: int | None = None,
        total_steps: int | None = None,
        last_error: str | None = None,
    ):
        if self.research_state is None:
            return None
        return await self.research_state.update_job_phase(
            job_id,
            phase=phase,
            current_step=current_step,
            total_steps=total_steps,
            last_error=last_error,
        )

    async def append_finding(self, job_id: str, findings: list[dict], references: list[dict]):
        if self.research_state is None:
            return None
        return await self.research_state.append_step(
            job_id,
            findings_json=json.dumps(findings, ensure_ascii=False),
            references_json=json.dumps(references, ensure_ascii=False),
        )

    async def save_report(self, job_id: str, report_markdown: str):
        if self.research_state is None:
            return None
        return await self.research_state.save_report(job_id, report_markdown)

    async def fail_job(self, job_id: str, error_message: str):
        if self.research_state is None:
            return None
        return await self.research_state.fail_job(job_id, error_message)
