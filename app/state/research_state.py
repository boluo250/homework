from __future__ import annotations

from typing import Any

from app.core.models import ResearchJob, ResearchJobState, utc_now_iso
from app.services.d1_repo import AppRepository


class ResearchState:
    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    async def create_job(self, user_id: str, query: str) -> ResearchJob:
        return await self.repository.create_research_job(user_id, query)

    async def get_job(self, job_id: str) -> ResearchJob | None:
        return await self.repository.get_research_job(job_id)

    async def list_jobs(self, user_id: str) -> list[ResearchJob]:
        if hasattr(self.repository, "research_jobs_by_id"):
            jobs = getattr(self.repository, "research_jobs_by_id", {})
            return [job for job in jobs.values() if job.user_id == user_id]
        if hasattr(self.repository, "_fetchall"):
            rows = self.repository._fetchall(  # type: ignore[attr-defined]
                "SELECT * FROM research_jobs WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC",
                (user_id,),
            )
            return [_row_to_research_job(row) for row in rows]
        if hasattr(self.repository, "_all"):
            rows = await self.repository._all(  # type: ignore[attr-defined]
                "SELECT * FROM research_jobs WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC",
                (user_id,),
            )
            return [_row_to_research_job(row) for row in rows]
        return []

    async def update_job_phase(
        self,
        job_id: str,
        *,
        phase: str,
        current_step: int | None = None,
        total_steps: int | None = None,
        last_error: str | None = None,
        completed_at: str | None = None,
    ) -> ResearchJobState | None:
        return await self.repository.update_research_job_state(
            job_id,
            phase=phase,
            current_step=current_step,
            total_steps=total_steps,
            last_error=last_error,
            completed_at=completed_at,
        )

    async def append_step(
        self,
        job_id: str,
        *,
        findings_json: str | None = None,
        references_json: str | None = None,
    ) -> ResearchJobState | None:
        return await self.repository.update_research_job_state(
            job_id,
            findings_json=findings_json,
            references_json=references_json,
        )

    async def save_report(self, job_id: str, report_markdown: str) -> ResearchJob | None:
        return await self.repository.update_research_job(
            job_id,
            status="completed",
            report_markdown=report_markdown,
        )

    async def fail_job(self, job_id: str, error_message: str) -> ResearchJob | None:
        await self.repository.update_research_job_state(
            job_id,
            phase="failed",
            last_error=error_message,
            completed_at=utc_now_iso(),
        )
        return await self.repository.update_research_job(
            job_id,
            status="failed",
            report_markdown=f"# 研究失败\n\n- 原因：{error_message}",
        )

    async def clear_jobs(self, user_id: str) -> int:
        if hasattr(self.repository, "research_jobs_by_id"):
            jobs = getattr(self.repository, "research_jobs_by_id", {})
            states = getattr(self.repository, "research_job_states_by_id", {})
            targets = [job_id for job_id, job in jobs.items() if job.user_id == user_id]
            for job_id in targets:
                jobs.pop(job_id, None)
                states.pop(job_id, None)
            return len(targets)
        if hasattr(self.repository, "_execute"):
            self.repository._execute(  # type: ignore[attr-defined]
                "DELETE FROM research_job_states WHERE job_id IN (SELECT id FROM research_jobs WHERE user_id = ?)",
                (user_id,),
            )
            self.repository._execute(  # type: ignore[attr-defined]
                "DELETE FROM research_jobs WHERE user_id = ?",
                (user_id,),
            )
            return 0
        if hasattr(self.repository, "_run"):
            await self.repository._run(  # type: ignore[attr-defined]
                "DELETE FROM research_job_states WHERE job_id IN (SELECT id FROM research_jobs WHERE user_id = ?)",
                (user_id,),
            )
            await self.repository._run(  # type: ignore[attr-defined]
                "DELETE FROM research_jobs WHERE user_id = ?",
                (user_id,),
            )
            return 0
        return 0


def _row_to_research_job(row: Any) -> ResearchJob:
    return ResearchJob(
        id=row["id"],
        user_id=row["user_id"],
        query=row["query"],
        status=row["status"],
        report_markdown=row["report_markdown"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
