from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from typing import Any

from app.core.models import utc_now_iso
from app.providers.llm_base import ChatProviderBase
from app.services.d1_repo import AppRepository
from app.services.research_agent import ResearchAgent, ResearchPlanStep, ResearchStepResult
from app.services.search_service import SearchService
from app.services.web_fetch_service import WebFetchService


class ResearchService:
    def __init__(
        self,
        repository: AppRepository,
        search_service: SearchService,
        web_fetch_service: WebFetchService,
        chat_provider: ChatProviderBase | None = None,
        queue_binding: Any | None = None,
        stalled_job_timeout_seconds: float = 8.0,
    ) -> None:
        self.repository = repository
        self.agent = ResearchAgent(
            search_service=search_service,
            web_fetch_service=web_fetch_service,
            chat_provider=chat_provider,
        )
        self.queue_binding = queue_binding
        self.stalled_job_timeout_seconds = max(0.0, stalled_job_timeout_seconds)
        self.running_jobs: dict[str, asyncio.Task] = {}
        self.progress_locks: dict[str, asyncio.Lock] = {}

    async def submit(self, *, client_id: str, query: str) -> dict:
        user = await self.repository.get_or_create_user(client_id)
        plan = self.agent.build_plan(query)
        self._log(
            "submit.start",
            client_id=client_id,
            user_id=user.id,
            query=query,
            total_steps=len(plan),
            queue_enabled=self.queue_binding is not None,
        )
        initial_report = self.agent.render_progress_markdown(
            query=query,
            plan=plan,
            completed_steps=0,
            active_step=1 if plan else None,
            phase_text="研究任务已入队，等待后台消费者开始执行",
            findings=[],
        )

        job = await self.repository.create_research_job(user.id, query)
        await self.repository.update_research_job(
            job.id,
            status="queued",
            report_markdown=initial_report,
        )
        await self.repository.create_research_job_state(
            job.id,
            phase="queued",
            current_step=0,
            total_steps=len(plan),
            plan_json=_serialize_plan(plan),
            findings_json="[]",
            references_json="[]",
        )
        self._log("submit.persisted", job_id=job.id, user_id=user.id, total_steps=len(plan))

        if self.queue_binding is not None:
            self._log("submit.enqueue", job_id=job.id, queue_mode="cloudflare_queue")
            await self.queue_binding.send(json.dumps({"job_id": job.id}))
        else:
            self._log("submit.local_start", job_id=job.id, queue_mode="local_task")
            self.running_jobs[job.id] = asyncio.create_task(self._run_job_locally(job.id))
        return await self.get(job.id) or job.to_dict()

    async def get(self, job_id: str, *, drive_stalled: bool = False) -> dict | None:
        self._log("get.start", job_id=job_id, drive_stalled=drive_stalled)
        if drive_stalled:
            await self._resume_stalled_job(job_id)
        job = await self.repository.get_research_job(job_id)
        if not job:
            self._log("get.missing", job_id=job_id)
            return None
        payload = job.to_dict()
        state = await self.repository.get_research_job_state(job_id)
        if state:
            payload["phase"] = state.phase
            payload["current_step"] = state.current_step
            payload["total_steps"] = state.total_steps
            payload["last_error"] = state.last_error
            payload["state"] = state.to_dict()
            self._log(
                "get.state",
                job_id=job_id,
                status=job.status,
                phase=state.phase,
                current_step=state.current_step,
                total_steps=state.total_steps,
            )
        return payload

    async def process_queue_message(self, message_body: Any) -> None:
        payload = _normalize_queue_message(message_body)
        job_id = str(payload.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("Queue message missing job_id")
        self._log("queue.consume", job_id=job_id, payload=payload)
        done = await self._process_one_transition(job_id)
        if not done and self.queue_binding is not None:
            self._log("queue.requeue", job_id=job_id)
            await self.queue_binding.send(json.dumps({"job_id": job_id}))
        else:
            self._log("queue.done", job_id=job_id, done=done)

    async def mark_retry(self, job_id: str, error: str) -> None:
        self._log("job.retry", job_id=job_id, error=error[:500])
        state = await self.repository.get_research_job_state(job_id)
        current_phase = state.phase if state else "retrying"
        await self.repository.update_research_job_state(
            job_id,
            phase=current_phase,
            last_error=error,
        )
        job = await self.repository.get_research_job(job_id)
        current_report = job.report_markdown if job else None
        await self.repository.update_research_job(
            job_id,
            status="running",
            report_markdown=current_report,
        )

    async def mark_failed(self, job_id: str, error: str) -> None:
        self._log("job.failed", job_id=job_id, error=error[:1000])
        await self.repository.update_research_job_state(
            job_id,
            phase="failed",
            last_error=error,
            completed_at=utc_now_iso(),
        )
        await self.repository.update_research_job(
            job_id,
            status="failed",
            report_markdown=f"# 研究失败\n\n- 状态：failed\n- 原因：{error}",
        )

    async def _run_job_locally(self, job_id: str) -> None:
        self._log("local_runner.start", job_id=job_id)
        try:
            while True:
                done = await self._process_one_transition(job_id)
                if done:
                    self._log("local_runner.complete", job_id=job_id)
                    return
                await asyncio.sleep(0)
        except Exception as exc:
            self._log("local_runner.error", job_id=job_id, error=str(exc))
            await self.mark_failed(job_id, str(exc))
        finally:
            self.running_jobs.pop(job_id, None)

    async def _resume_stalled_job(self, job_id: str) -> None:
        if self.queue_binding is None:
            return
        state = await self.repository.get_research_job_state(job_id)
        if not state:
            self._log("resume.skip_missing_state", job_id=job_id)
            return
        stalled = _is_stalled(state.updated_at, timeout_seconds=self.stalled_job_timeout_seconds)
        self._log(
            "resume.inspect",
            job_id=job_id,
            phase=state.phase,
            current_step=state.current_step,
            total_steps=state.total_steps,
            updated_at=state.updated_at,
            stalled=stalled,
        )
        if not stalled:
            return
        try:
            self._log("resume.run", job_id=job_id)
            await self._process_one_transition(job_id)
        except Exception as exc:
            self._log("resume.error", job_id=job_id, error=str(exc))
            await self.mark_failed(job_id, str(exc))

    async def _process_one_transition(self, job_id: str) -> bool:
        async with self._progress_lock(job_id):
            self._log("transition.locked", job_id=job_id)
            return await self._process_next_transition(job_id)

    def _progress_lock(self, job_id: str) -> asyncio.Lock:
        lock = self.progress_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self.progress_locks[job_id] = lock
        return lock

    async def _process_next_transition(self, job_id: str) -> bool:
        job = await self.repository.get_research_job(job_id)
        state = await self.repository.get_research_job_state(job_id)
        if not job or not state:
            self._log("transition.skip_missing", job_id=job_id, has_job=bool(job), has_state=bool(state))
            return True
        if job.status in {"completed", "failed"}:
            self._log("transition.skip_terminal", job_id=job_id, status=job.status)
            return True

        plan = _deserialize_plan(state.plan_json)
        findings = _deserialize_findings(state.findings_json)
        references = _deserialize_references(state.references_json)
        started_at = state.started_at or utc_now_iso()
        self._log(
            "transition.start",
            job_id=job_id,
            status=job.status,
            phase=state.phase,
            current_step=state.current_step,
            total_steps=len(plan),
            findings_count=len(findings),
            references_count=len(references),
        )

        if state.current_step < len(plan):
            step_index = state.current_step
            step = plan[step_index]
            self._log(
                "step.begin",
                job_id=job_id,
                step_index=step_index + 1,
                total_steps=len(plan),
                step_title=step.title,
            )
            await self.repository.update_research_job_state(
                job_id,
                phase="searching",
                started_at=started_at,
            )
            await self.repository.update_research_job(
                job_id,
                status="running",
                report_markdown=self.agent.render_progress_markdown(
                    query=job.query,
                    plan=plan,
                    completed_steps=step_index,
                    active_step=step_index + 1,
                    phase_text=f"正在执行子代理：{step.title}",
                    findings=findings,
                ),
            )
            step_result = await self.agent.execute_step(query=job.query, step=step)
            self._log(
                "step.result",
                job_id=job_id,
                step_index=step_index + 1,
                total_steps=len(plan),
                step_title=step.title,
                source_count=len(step_result.sources),
                finding_count=len(step_result.findings),
            )
            findings.append(step_result)
            references.extend(step_result.sources)
            next_step = step_index + 1
            await self.repository.update_research_job_state(
                job_id,
                phase="queued" if next_step < len(plan) else "synthesizing",
                current_step=next_step,
                total_steps=len(plan),
                findings_json=_serialize_findings(findings),
                references_json=json.dumps(references, ensure_ascii=False),
                started_at=started_at,
                last_error=None,
            )
            await self.repository.update_research_job(
                job_id,
                status="running",
                report_markdown=self.agent.render_progress_markdown(
                    query=job.query,
                    plan=plan,
                    completed_steps=next_step,
                    active_step=next_step + 1 if next_step < len(plan) else None,
                    phase_text="正在等待下一阶段继续执行" if next_step < len(plan) else "正在准备汇总最终报告",
                    findings=findings,
                ),
            )
            self._log(
                "step.persisted",
                job_id=job_id,
                completed_steps=next_step,
                total_steps=len(plan),
                next_phase="queued" if next_step < len(plan) else "synthesizing",
            )
            return False

        self._log("synthesis.begin", job_id=job_id, total_steps=len(plan), references_count=len(references))
        await self.repository.update_research_job_state(
            job_id,
            phase="synthesizing",
            started_at=started_at,
        )
        await self.repository.update_research_job(
            job_id,
            status="running",
            report_markdown=self.agent.render_progress_markdown(
                query=job.query,
                plan=plan,
                completed_steps=len(plan),
                active_step=None,
                phase_text="正在汇总结构化研究报告",
                findings=findings,
            ),
        )
        final_report = await self.agent.synthesize_report(
            query=job.query,
            plan=plan,
            findings=findings,
            references=references,
        )
        self._log("synthesis.done", job_id=job_id, report_length=len(final_report or ""))
        completed_at = utc_now_iso()
        await self.repository.update_research_job_state(
            job_id,
            phase="completed",
            current_step=len(plan),
            total_steps=len(plan),
            findings_json=_serialize_findings(findings),
            references_json=json.dumps(references, ensure_ascii=False),
            started_at=started_at,
            completed_at=completed_at,
            last_error=None,
        )
        await self.repository.update_research_job(
            job_id,
            status="completed",
            report_markdown=final_report,
        )
        self._log("job.completed", job_id=job_id, total_steps=len(plan), completed_at=completed_at)
        return True

    def _log(self, event: str, **fields: Any) -> None:
        payload = {"scope": "research", "event": event, **fields}
        try:
            print(f"[taskmate] {json.dumps(payload, ensure_ascii=False, default=str)}")
        except Exception:  # noqa: BLE001
            print(f"[taskmate] research event={event} fields={fields!r}")


def _serialize_plan(plan: list[ResearchPlanStep]) -> str:
    return json.dumps(
        [
            {
                "title": item.title,
                "objective": item.objective,
                "search_queries": item.search_queries,
            }
            for item in plan
        ],
        ensure_ascii=False,
    )


def _deserialize_plan(payload: str | None) -> list[ResearchPlanStep]:
    if not payload:
        return []
    raw_items = json.loads(payload)
    return [
        ResearchPlanStep(
            title=str(item.get("title", "")),
            objective=str(item.get("objective", "")),
            search_queries=list(item.get("search_queries", [])),
        )
        for item in raw_items
    ]


def _serialize_findings(findings: list[ResearchStepResult]) -> str:
    return json.dumps(
        [
            {
                "step": {
                    "title": item.step.title,
                    "objective": item.step.objective,
                    "search_queries": item.step.search_queries,
                },
                "sources": item.sources,
                "findings": item.findings,
            }
            for item in findings
        ],
        ensure_ascii=False,
    )


def _deserialize_findings(payload: str | None) -> list[ResearchStepResult]:
    if not payload:
        return []
    raw_items = json.loads(payload)
    findings = []
    for item in raw_items:
        step_raw = item.get("step", {})
        findings.append(
            ResearchStepResult(
                step=ResearchPlanStep(
                    title=str(step_raw.get("title", "")),
                    objective=str(step_raw.get("objective", "")),
                    search_queries=list(step_raw.get("search_queries", [])),
                ),
                sources=list(item.get("sources", [])),
                findings=list(item.get("findings", [])),
            )
        )
    return findings


def _deserialize_references(payload: str | None) -> list[dict]:
    if not payload:
        return []
    return list(json.loads(payload))


def _normalize_queue_message(message_body: Any) -> dict:
    # Try to_py() first (Pyodide JS proxy)
    if hasattr(message_body, "to_py"):
        try:
            converted = message_body.to_py()
            if isinstance(converted, dict):
                return converted
            if isinstance(converted, str):
                return json.loads(converted)
            message_body = converted
        except Exception:  # noqa: BLE001
            pass

    if isinstance(message_body, dict):
        return message_body
    if isinstance(message_body, str):
        return json.loads(message_body)

    # JS object with attribute access (Pyodide proxy that didn't convert cleanly)
    job_id = None
    for attr in ("job_id",):
        try:
            val = getattr(message_body, attr, None)
            if val is None and hasattr(message_body, "get"):
                val = message_body.get(attr)
            if val is not None:
                job_id = str(val)
                break
        except Exception:  # noqa: BLE001
            pass

    if job_id:
        return {"job_id": job_id}

    raise ValueError(f"Unsupported queue message body: {type(message_body)!r}")


def _is_stalled(updated_at: str | None, *, timeout_seconds: float) -> bool:
    if timeout_seconds <= 0:
        return True
    if not updated_at:
        return True
    try:
        updated_dt = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if updated_dt.tzinfo is None:
        updated_dt = updated_dt.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - updated_dt.astimezone(timezone.utc)).total_seconds()
    return age_seconds >= timeout_seconds
