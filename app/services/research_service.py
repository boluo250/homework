from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from typing import Any

from app.core.models import utc_now_iso
from app.providers.llm_base import ChatProviderBase
from app.services.d1_repo import AppRepository
from app.services.research_agent import ResearchAgent, ResearchPlan, ResearchPlanStep, ResearchStepResult
from app.services.search_service import SearchService
from app.services.web_fetch_service import WebFetchService

RESEARCH_RUNTIME_VERSION = "research-fix-2026-04-22-04"
QUEUE_TYPE_ORCHESTRATE = "research_orchestrate"
QUEUE_TYPE_SUB_RUN = "research_sub_run"
QUEUE_TYPE_SYNTHESIZE = "research_synthesize"


class ResearchService:
    def __init__(
        self,
        repository: AppRepository,
        search_service: SearchService,
        web_fetch_service: WebFetchService,
        chat_provider: ChatProviderBase | None = None,
        queue_binding: Any | None = None,
        stalled_job_timeout_seconds: float = 8.0,
        synthesis_stall_timeout_seconds: float = 40.0,
    ) -> None:
        self.repository = repository
        self.agent = ResearchAgent(
            search_service=search_service,
            web_fetch_service=web_fetch_service,
            chat_provider=chat_provider,
            log_callback=self._log_from_agent,
        )
        self.queue_binding = queue_binding
        self.stalled_job_timeout_seconds = max(0.0, stalled_job_timeout_seconds)
        self.synthesis_stall_timeout_seconds = max(0.0, synthesis_stall_timeout_seconds)
        self.running_jobs: dict[str, asyncio.Task] = {}
        self.progress_locks: dict[str, asyncio.Lock] = {}

    async def submit(self, *, client_id: str, query: str) -> dict:
        user = await self.repository.get_or_create_user(client_id)
        research_plan = self.agent.build_research_plan(query)
        plan = research_plan.steps
        self._log(
            "submit.start",
            client_id=client_id,
            user_id=user.id,
            query=query,
            total_steps=len(plan),
            queue_enabled=self.queue_binding is not None,
            profile=research_plan.profile,
        )
        initial_report = self.agent.render_progress_markdown(
            query=query,
            plan=plan,
            completed_steps=0,
            active_step=1 if plan else None,
            phase_text="研究任务已提交，正在建立子代理执行计划",
            findings=[],
            profile_label=research_plan.profile_label,
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
            plan_json=_serialize_research_plan(research_plan),
            findings_json="[]",
            references_json="[]",
        )
        for index, step in enumerate(plan, start=1):
            await self.repository.create_research_sub_run(
                job.id,
                title=step.title,
                objective=step.objective,
                profile=research_plan.profile,
                strategy_id=step.strategy_id,
                step_index=index,
                search_queries_json=json.dumps(step.search_queries, ensure_ascii=False),
            )
        await self.repository.append_research_event(
            job.id,
            event_type="job_submitted",
            payload_json=json.dumps(
                {
                    "query": query,
                    "profile": research_plan.profile,
                    "profile_label": research_plan.profile_label,
                    "sub_run_count": len(plan),
                },
                ensure_ascii=False,
            ),
        )
        self._log("submit.persisted", job_id=job.id, user_id=user.id, total_steps=len(plan))

        if self.queue_binding is not None:
            self._log("submit.enqueue", job_id=job.id, queue_mode="cloudflare_queue")
            await self.queue_binding.send(json.dumps({"type": QUEUE_TYPE_ORCHESTRATE, "job_id": job.id}))
        else:
            self._log("submit.local_start", job_id=job.id, queue_mode="local_task")
            self.running_jobs[job.id] = asyncio.create_task(self._run_job_locally(job.id))
        return await self.get(job.id) or job.to_dict()

    async def get(self, job_id: str, *, drive_stalled: bool = False) -> dict | None:
        self._log("get.start", job_id=job_id, drive_stalled=drive_stalled)
        if drive_stalled:
            await self._drive_stalled_job(job_id)
        job = await self.repository.get_research_job(job_id)
        if not job:
            self._log("get.missing", job_id=job_id)
            return None
        state = await self.repository.get_research_job_state(job_id)
        if state and state.phase == "synthesizing":
            recovered = await self._recover_stalled_synthesis(job_id)
            if recovered:
                job = await self.repository.get_research_job(job_id) or job
                state = await self.repository.get_research_job_state(job_id) or state
        payload = job.to_dict()
        plan_bundle = _deserialize_research_plan(state.plan_json if state else None)
        sub_runs = [item.to_dict() for item in await self.repository.list_research_sub_runs(job_id)]
        events = [item.to_dict() for item in await self.repository.list_research_events(job_id)]
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
        payload["research_profile"] = plan_bundle.profile
        payload["research_profile_label"] = plan_bundle.profile_label
        payload["research_rationale"] = plan_bundle.rationale
        payload["sub_runs"] = sub_runs
        payload["events"] = events
        return payload

    async def process_queue_message(self, message_body: Any) -> None:
        payload = _normalize_queue_message(message_body)
        message_type = str(payload.get("type", QUEUE_TYPE_ORCHESTRATE)).strip() or QUEUE_TYPE_ORCHESTRATE
        job_id = str(payload.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("Queue message missing job_id")
        self._log("queue.consume", job_id=job_id, payload=payload, type=message_type)
        if message_type == QUEUE_TYPE_ORCHESTRATE:
            await self._dispatch_pending_sub_runs(job_id, enqueue=True)
            return
        if message_type == QUEUE_TYPE_SUB_RUN:
            sub_run_id = str(payload.get("sub_run_id", "")).strip()
            if not sub_run_id:
                raise ValueError("Queue sub-run message missing sub_run_id")
            await self._execute_sub_run(job_id, sub_run_id)
            if await self._all_sub_runs_terminal(job_id) and self.queue_binding is not None:
                await self.queue_binding.send(json.dumps({"type": QUEUE_TYPE_SYNTHESIZE, "job_id": job_id}))
            return
        if message_type == QUEUE_TYPE_SYNTHESIZE:
            if await self._all_sub_runs_terminal(job_id):
                await self._synthesize_job(job_id)
            return
        raise ValueError(f"Unsupported queue message type: {message_type}")

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
            await self._dispatch_pending_sub_runs(job_id, enqueue=False)
            while True:
                job = await self.repository.get_research_job(job_id)
                if not job or job.status in {"completed", "failed"}:
                    self._log("local_runner.complete", job_id=job_id)
                    return
                pending = [item for item in await self.repository.list_research_sub_runs(job_id) if item.status == "queued"]
                if pending:
                    await self._execute_sub_run(job_id, pending[0].id)
                    await asyncio.sleep(0)
                    continue
                if await self._all_sub_runs_terminal(job_id):
                    await self._synthesize_job(job_id)
                    self._log("local_runner.complete", job_id=job_id)
                    return
                await asyncio.sleep(0)
        except Exception as exc:
            self._log("local_runner.error", job_id=job_id, error=str(exc))
            await self.mark_failed(job_id, str(exc))
        finally:
            self.running_jobs.pop(job_id, None)

    async def _drive_stalled_job(self, job_id: str) -> None:
        if self.queue_binding is None:
            return
        state = await self.repository.get_research_job_state(job_id)
        job = await self.repository.get_research_job(job_id)
        if not state:
            self._log("drive.skip_missing_state", job_id=job_id)
            return
        if not job or job.status in {"completed", "failed"}:
            return
        stalled = _is_stalled(state.updated_at, timeout_seconds=self.stalled_job_timeout_seconds)
        if not stalled:
            return
        try:
            sub_runs = await self.repository.list_research_sub_runs(job_id)
            if state.phase in {"queued", "planning"}:
                await self._dispatch_pending_sub_runs(job_id, enqueue=False)
                return
            pending = [item for item in sub_runs if item.status == "queued"]
            if pending:
                await self._execute_sub_run(job_id, pending[0].id)
                return
            if await self._all_sub_runs_terminal(job_id):
                await self._synthesize_job(job_id)
        except Exception as exc:
            self._log("drive.error", job_id=job_id, error=str(exc))
            await self.mark_failed(job_id, str(exc))

    async def _recover_stalled_synthesis(self, job_id: str) -> bool:
        state = await self.repository.get_research_job_state(job_id)
        job = await self.repository.get_research_job(job_id)
        if not state or not job:
            return False
        stalled = _is_stalled(state.updated_at, timeout_seconds=self.synthesis_stall_timeout_seconds)
        self._log(
            "synthesis.inspect",
            job_id=job_id,
            status=job.status,
            phase=state.phase,
            current_step=state.current_step,
            total_steps=state.total_steps,
            updated_at=state.updated_at,
            stalled=stalled,
            timeout_seconds=self.synthesis_stall_timeout_seconds,
        )
        if state.phase != "synthesizing" or job.status in {"completed", "failed"} or not stalled:
            return False

        async with self._progress_lock(job_id):
            latest_state = await self.repository.get_research_job_state(job_id)
            latest_job = await self.repository.get_research_job(job_id)
            if not latest_state or not latest_job:
                return False
            if latest_state.phase != "synthesizing" or latest_job.status in {"completed", "failed"}:
                return False
            if not _is_stalled(latest_state.updated_at, timeout_seconds=self.synthesis_stall_timeout_seconds):
                return False

            plan_bundle = _deserialize_research_plan(latest_state.plan_json)
            findings = _deserialize_findings(latest_state.findings_json)
            references = _deserialize_references(latest_state.references_json)
            self._log(
                "synthesis.force_fallback",
                job_id=job_id,
                findings_count=len(findings),
                references_count=len(references),
            )
            fallback_report = self.agent.render_fallback_report(
                query=latest_job.query,
                plan=plan_bundle.steps,
                findings=findings,
                references=references,
                profile_label=plan_bundle.profile_label,
            )
            fallback_report = (
                "# 研究报告\n\n"
                "> 检测到最终汇总阶段长时间未完成，已自动切换为本地汇总结果。\n\n"
                + fallback_report.removeprefix("# 研究报告\n\n")
            )
            completed_at = utc_now_iso()
            await self.repository.update_research_job_state(
                job_id,
                phase="completed",
                current_step=latest_state.total_steps or len(plan_bundle.steps),
                total_steps=latest_state.total_steps or len(plan_bundle.steps),
                findings_json=_serialize_findings(findings),
                references_json=json.dumps(references, ensure_ascii=False),
                started_at=latest_state.started_at,
                completed_at=completed_at,
                last_error="Final synthesis stalled; completed with local fallback report.",
            )
            await self.repository.update_research_job(
                job_id,
                status="completed",
                report_markdown=fallback_report,
            )
            self._log("job.completed_fallback", job_id=job_id, completed_at=completed_at)
            return True

    async def _dispatch_pending_sub_runs(self, job_id: str, *, enqueue: bool) -> None:
        async with self._progress_lock(job_id):
            job = await self.repository.get_research_job(job_id)
            state = await self.repository.get_research_job_state(job_id)
            if not job or not state or job.status in {"completed", "failed"}:
                return
            plan_bundle = _deserialize_research_plan(state.plan_json)
            sub_runs = await self.repository.list_research_sub_runs(job_id)
            if not sub_runs:
                return
            await self.repository.update_research_job_state(job_id, phase="orchestrating", started_at=state.started_at or utc_now_iso())
            await self.repository.update_research_job(
                job_id,
                status="running",
                report_markdown=self.agent.render_progress_markdown(
                    query=job.query,
                    plan=plan_bundle.steps,
                    completed_steps=0,
                    active_step=1 if sub_runs else None,
                    phase_text="父 orchestrator 已创建子代理，等待开始执行",
                    findings=[],
                    profile_label=plan_bundle.profile_label,
                    sub_runs=[item.to_dict() for item in sub_runs],
                ),
            )
            await self.repository.append_research_event(
                job_id,
                event_type="orchestrated",
                payload_json=json.dumps({"sub_run_count": len(sub_runs)}, ensure_ascii=False),
            )
            if enqueue and self.queue_binding is not None:
                for item in sub_runs:
                    await self.queue_binding.send(
                        json.dumps({"type": QUEUE_TYPE_SUB_RUN, "job_id": job_id, "sub_run_id": item.id})
                    )

    async def _execute_sub_run(self, job_id: str, sub_run_id: str) -> None:
        async with self._progress_lock(job_id):
            job = await self.repository.get_research_job(job_id)
            state = await self.repository.get_research_job_state(job_id)
            sub_run = await self.repository.get_research_sub_run(sub_run_id)
            if not job or not state or not sub_run:
                return
            if job.status in {"completed", "failed"} or sub_run.status in {"completed", "failed", "skipped"}:
                return
            plan_bundle = _deserialize_research_plan(state.plan_json)
            step = _step_from_sub_run(sub_run)
            started_at = utc_now_iso()
            await self.repository.update_research_sub_run(
                sub_run_id,
                status="running",
                started_at=started_at,
                last_error=None,
            )
            findings = _deserialize_findings(state.findings_json)
            await self.repository.update_research_job_state(job_id, phase="running", started_at=state.started_at or started_at)
            await self.repository.update_research_job(
                job_id,
                status="running",
                report_markdown=self.agent.render_progress_markdown(
                    query=job.query,
                    plan=plan_bundle.steps,
                    completed_steps=state.current_step,
                    active_step=sub_run.step_index,
                    phase_text=f"正在执行子代理：{sub_run.title}",
                    findings=findings,
                    profile_label=plan_bundle.profile_label,
                    sub_runs=[item.to_dict() for item in await self.repository.list_research_sub_runs(job_id)],
                ),
            )
            await self.repository.append_research_event(
                job_id,
                event_type="sub_run_started",
                sub_run_id=sub_run_id,
                payload_json=json.dumps({"title": sub_run.title, "step_index": sub_run.step_index}, ensure_ascii=False),
            )
            try:
                step_result = await self.agent.execute_step(query=job.query, step=step)
            except Exception as exc:
                completed_at = utc_now_iso()
                await self.repository.update_research_sub_run(
                    sub_run_id,
                    status="failed",
                    summary=str(exc)[:300],
                    last_error=str(exc),
                    completed_at=completed_at,
                )
                await self.repository.append_research_event(
                    job_id,
                    event_type="sub_run_failed",
                    sub_run_id=sub_run_id,
                    payload_json=json.dumps({"title": sub_run.title, "error": str(exc)}, ensure_ascii=False),
                )
                raise

            artifacts = {
                "summary": step_result.summary,
                "confidence": step_result.confidence,
                "gaps": step_result.gaps,
                "findings": step_result.findings,
                "sources": step_result.sources,
            }
            completed_at = utc_now_iso()
            await self.repository.update_research_sub_run(
                sub_run_id,
                status="completed",
                summary=step_result.summary,
                artifacts_json=json.dumps(artifacts, ensure_ascii=False),
                completed_at=completed_at,
            )
            await self.repository.append_research_event(
                job_id,
                event_type="sub_run_completed",
                sub_run_id=sub_run_id,
                payload_json=json.dumps(
                    {
                        "title": sub_run.title,
                        "source_count": len(step_result.sources),
                        "finding_count": len(step_result.findings),
                    },
                    ensure_ascii=False,
                ),
            )
            all_sub_runs = await self.repository.list_research_sub_runs(job_id)
            completed_count = sum(1 for item in all_sub_runs if item.status == "completed")
            aggregated_findings, aggregated_references = await self._aggregate_step_outputs(job_id)
            next_phase = "synthesizing" if await self._all_sub_runs_terminal(job_id) else "queued"
            await self.repository.update_research_job_state(
                job_id,
                phase=next_phase,
                current_step=completed_count,
                total_steps=len(all_sub_runs),
                findings_json=_serialize_findings(aggregated_findings),
                references_json=json.dumps(aggregated_references, ensure_ascii=False),
                started_at=state.started_at or started_at,
                last_error=None,
            )
            await self.repository.update_research_job(
                job_id,
                status="running",
                report_markdown=self.agent.render_progress_markdown(
                    query=job.query,
                    plan=plan_bundle.steps,
                    completed_steps=completed_count,
                    active_step=None if next_phase == "synthesizing" else completed_count + 1,
                    phase_text="正在准备汇总最终报告" if next_phase == "synthesizing" else "正在等待下一阶段继续执行",
                    findings=aggregated_findings,
                    profile_label=plan_bundle.profile_label,
                    sub_runs=[item.to_dict() for item in all_sub_runs],
                ),
            )

    async def _aggregate_step_outputs(self, job_id: str) -> tuple[list[ResearchStepResult], list[dict]]:
        sub_runs = await self.repository.list_research_sub_runs(job_id)
        findings: list[ResearchStepResult] = []
        references: list[dict] = []
        for item in sub_runs:
            payload = _deserialize_artifacts(item.artifacts_json)
            if not payload:
                continue
            step = _step_from_sub_run(item)
            findings.append(
                ResearchStepResult(
                    step=step,
                    sources=list(payload.get("sources", [])),
                    findings=list(payload.get("findings", [])),
                    summary=str(payload.get("summary", "") or ""),
                    confidence=str(payload.get("confidence", "medium") or "medium"),
                    gaps=list(payload.get("gaps", [])),
                )
            )
            references.extend(list(payload.get("sources", [])))
        return findings, references

    async def _all_sub_runs_terminal(self, job_id: str) -> bool:
        sub_runs = await self.repository.list_research_sub_runs(job_id)
        return bool(sub_runs) and all(item.status in {"completed", "failed", "skipped"} for item in sub_runs)

    async def _synthesize_job(self, job_id: str) -> None:
        async with self._progress_lock(job_id):
            job = await self.repository.get_research_job(job_id)
            state = await self.repository.get_research_job_state(job_id)
            if not job or not state or job.status in {"completed", "failed"}:
                return
            plan_bundle = _deserialize_research_plan(state.plan_json)
            findings, references = await self._aggregate_step_outputs(job_id)
            sub_runs = await self.repository.list_research_sub_runs(job_id)
            await self.repository.update_research_job_state(job_id, phase="synthesizing", started_at=state.started_at or utc_now_iso())
            await self.repository.update_research_job(
                job_id,
                status="running",
                report_markdown=self.agent.render_progress_markdown(
                    query=job.query,
                    plan=plan_bundle.steps,
                    completed_steps=len(sub_runs),
                    active_step=None,
                    phase_text="正在汇总结构化研究报告",
                    findings=findings,
                    profile_label=plan_bundle.profile_label,
                    sub_runs=[item.to_dict() for item in sub_runs],
                ),
            )
            final_report = await self.agent.synthesize_report(
                query=job.query,
                plan=plan_bundle.steps,
                findings=findings,
                references=references,
                profile_label=plan_bundle.profile_label,
            )
            completed_at = utc_now_iso()
            await self.repository.update_research_job_state(
                job_id,
                phase="completed",
                current_step=len(sub_runs),
                total_steps=len(sub_runs),
                findings_json=_serialize_findings(findings),
                references_json=json.dumps(references, ensure_ascii=False),
                started_at=state.started_at or completed_at,
                completed_at=completed_at,
                last_error=None,
            )
            await self.repository.update_research_job(job_id, status="completed", report_markdown=final_report)
            await self.repository.append_research_event(
                job_id,
                event_type="report_completed",
                payload_json=json.dumps({"sub_run_count": len(sub_runs)}, ensure_ascii=False),
            )
            self._log("job.completed", job_id=job_id, total_steps=len(sub_runs), completed_at=completed_at)

    def _progress_lock(self, job_id: str) -> asyncio.Lock:
        lock = self.progress_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self.progress_locks[job_id] = lock
        return lock

    def _log(self, event: str, **fields: Any) -> None:
        payload = {
            "scope": "research",
            "event": event,
            "runtime_version": RESEARCH_RUNTIME_VERSION,
            **fields,
        }
        try:
            print(f"[taskmate] {json.dumps(payload, ensure_ascii=False, default=str)}")
        except Exception:  # noqa: BLE001
            print(f"[taskmate] research event={event} fields={fields!r}")

    def _log_from_agent(self, event: str, fields: dict[str, Any]) -> None:
        self._log(event, **fields)


def _serialize_research_plan(plan: ResearchPlan) -> str:
    return json.dumps(
        {
            "profile": plan.profile,
            "profile_label": plan.profile_label,
            "rationale": plan.rationale,
            "steps": [
                {
                    "title": item.title,
                    "objective": item.objective,
                    "search_queries": item.search_queries,
                    "strategy_id": item.strategy_id,
                    "allowed_domains": item.allowed_domains,
                    "tool_scope": item.tool_scope,
                    "model_tier": item.model_tier,
                    "max_sources": item.max_sources,
                }
                for item in plan.steps
            ],
        },
        ensure_ascii=False,
    )


def _deserialize_research_plan(payload: str | None) -> ResearchPlan:
    if not payload:
        return ResearchPlan(profile="mixed", profile_label="混合调研", rationale="", steps=[])
    raw = json.loads(payload)
    if isinstance(raw, list):
        return ResearchPlan(
            profile="mixed",
            profile_label="混合调研",
            rationale="兼容旧版 plan_json",
            steps=[_deserialize_step(item) for item in raw],
        )
    return ResearchPlan(
        profile=str(raw.get("profile", "mixed")),
        profile_label=str(raw.get("profile_label", "混合调研")),
        rationale=str(raw.get("rationale", "")),
        steps=[_deserialize_step(item) for item in list(raw.get("steps", []))],
    )


def _deserialize_step(item: dict[str, Any]) -> ResearchPlanStep:
    return ResearchPlanStep(
        title=str(item.get("title", "")),
        objective=str(item.get("objective", "")),
        search_queries=list(item.get("search_queries", [])),
        strategy_id=str(item.get("strategy_id", "general_web")),
        allowed_domains=list(item.get("allowed_domains", [])),
        tool_scope=list(item.get("tool_scope", ["search", "fetch"])),
        model_tier=str(item.get("model_tier", "default")),
        max_sources=int(item.get("max_sources", 4) or 4),
    )


def _serialize_findings(findings: list[ResearchStepResult]) -> str:
    return json.dumps(
        [
            {
                "step": {
                    "title": item.step.title,
                    "objective": item.step.objective,
                    "search_queries": item.step.search_queries,
                    "strategy_id": item.step.strategy_id,
                    "allowed_domains": item.step.allowed_domains,
                    "tool_scope": item.step.tool_scope,
                    "model_tier": item.step.model_tier,
                    "max_sources": item.step.max_sources,
                },
                "sources": item.sources,
                "findings": item.findings,
                "summary": item.summary,
                "confidence": item.confidence,
                "gaps": item.gaps,
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
                step=_deserialize_step(step_raw),
                sources=list(item.get("sources", [])),
                findings=list(item.get("findings", [])),
                summary=str(item.get("summary", "") or ""),
                confidence=str(item.get("confidence", "medium") or "medium"),
                gaps=list(item.get("gaps", [])),
            )
        )
    return findings


def _deserialize_references(payload: str | None) -> list[dict]:
    if not payload:
        return []
    return list(json.loads(payload))


def _deserialize_artifacts(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    return dict(json.loads(payload))


def _step_from_sub_run(sub_run) -> ResearchPlanStep:
    return ResearchPlanStep(
        title=sub_run.title,
        objective=sub_run.objective,
        search_queries=json.loads(sub_run.search_queries_json or "[]"),
        strategy_id=sub_run.strategy_id,
    )


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
    for attr in ("job_id", "sub_run_id", "type"):
        try:
            val = getattr(message_body, attr, None)
            if val is None and hasattr(message_body, "get"):
                val = message_body.get(attr)
            if val is not None:
                if attr == "job_id":
                    job_id = str(val)
        except Exception:  # noqa: BLE001
            pass

    if job_id:
        payload = {"job_id": job_id}
        for attr in ("type", "sub_run_id"):
            try:
                val = getattr(message_body, attr, None)
                if val is None and hasattr(message_body, "get"):
                    val = message_body.get(attr)
                if val is not None:
                    payload[attr] = str(val)
            except Exception:  # noqa: BLE001
                pass
        return payload

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
