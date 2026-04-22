from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from app.providers.llm_base import ChatProviderBase
from app.services.search_service import SearchService
from app.services.web_fetch_service import WebFetchService


ProgressCallback = Callable[[str, str], Awaitable[None]]
ResearchLogCallback = Callable[[str, dict[str, Any]], None]


@dataclass(slots=True)
class ResearchPlanStep:
    title: str
    objective: str
    search_queries: list[str]


@dataclass(slots=True)
class ResearchStepResult:
    step: ResearchPlanStep
    sources: list[dict]
    findings: list[str]


class ResearchAgent:
    SYNTHESIS_TIMEOUT_SECONDS = 25.0

    def __init__(
        self,
        search_service: SearchService,
        web_fetch_service: WebFetchService,
        chat_provider: ChatProviderBase | None = None,
        log_callback: ResearchLogCallback | None = None,
    ) -> None:
        self.search_service = search_service
        self.web_fetch_service = web_fetch_service
        self.chat_provider = chat_provider
        self.log_callback = log_callback

    async def execute(self, *, query: str, on_progress: ProgressCallback) -> str:
        plan = self.build_plan(query)
        findings: list[ResearchStepResult] = []
        references: list[dict] = []

        await on_progress(
            "planning",
            self.render_progress_markdown(
                query=query,
                plan=plan,
                completed_steps=0,
                active_step=1,
                phase_text="正在拆解研究问题与检索路径",
                findings=findings,
            ),
        )

        for index, step in enumerate(plan, start=1):
            await on_progress(
                "searching",
                self.render_progress_markdown(
                    query=query,
                    plan=plan,
                    completed_steps=index - 1,
                    active_step=index,
                    phase_text=f"正在检索：{step.title}",
                    findings=findings,
                ),
            )
            step_result = await self._run_step(query=query, step=step)
            findings.append(step_result)
            references.extend(step_result.sources)
            await on_progress(
                "reading",
                self.render_progress_markdown(
                    query=query,
                    plan=plan,
                    completed_steps=index,
                    active_step=index + 1 if index < len(plan) else None,
                    phase_text=f"正在整理证据：{step.title}",
                    findings=findings,
                ),
            )

        await on_progress(
            "synthesizing",
            self.render_progress_markdown(
                query=query,
                plan=plan,
                completed_steps=len(plan),
                active_step=None,
                phase_text="正在汇总关键发现并生成结构化报告",
                findings=findings,
            ),
        )
        return await self._synthesize_report(query=query, plan=plan, findings=findings, references=references)

    async def execute_step(self, *, query: str, step: ResearchPlanStep) -> ResearchStepResult:
        return await self._run_step(query=query, step=step)

    async def synthesize_report(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
    ) -> str:
        return await self._synthesize_report(query=query, plan=plan, findings=findings, references=references)

    def render_fallback_report(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
    ) -> str:
        return _render_fallback_report(query=query, plan=plan, findings=findings, references=references)

    def build_plan(self, query: str) -> list[ResearchPlanStep]:
        lowered = query.lower()
        normalized = query.strip()
        steps = [
            ResearchPlanStep(
                title="界定问题与目标",
                objective="明确这次研究到底要解决什么问题、产出给谁看、评价标准是什么。",
                search_queries=[
                    normalized,
                    f"{normalized} goals scope evaluation criteria",
                ],
            ),
            ResearchPlanStep(
                title="收集候选实现方案",
                objective="找出当前主流做法、轻量方案和可替代技术路径。",
                search_queries=[
                    f"{normalized} implementation architecture",
                    f"{normalized} lightweight approach best practices",
                ],
            ),
            ResearchPlanStep(
                title="验证约束与边界",
                objective="确认运行时限制、存储约束、异步执行方式和第三方依赖风险。",
                search_queries=[
                    f"{normalized} runtime limits constraints",
                    f"{normalized} storage queue async limits",
                ],
            ),
            ResearchPlanStep(
                title="对比成本与风险",
                objective="比较不同路径的工程复杂度、成本、稳定性和演示效果。",
                search_queries=[
                    f"{normalized} tradeoffs cost risk comparison",
                    f"{normalized} production considerations pitfalls",
                ],
            ),
            ResearchPlanStep(
                title="形成建议与落地顺序",
                objective="收敛为推荐方案，并给出适合当前场景的实施顺序。",
                search_queries=[
                    f"{normalized} recommendation roadmap",
                    f"{normalized} implementation checklist",
                ],
            ),
        ]

        if "cloudflare" in lowered or "worker" in lowered:
            steps.insert(
                2,
                ResearchPlanStep(
                    title="核对 Cloudflare Worker 特性",
                    objective="确认 Worker 在 AI、检索、存储、文件处理上的适配方式和典型组合。",
                    search_queries=[
                        f"{normalized} Cloudflare Workers AI RAG",
                        f"{normalized} D1 R2 Vectorize Qdrant",
                    ],
                ),
            )

        return steps[:6]

    def render_progress_markdown(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        completed_steps: int,
        active_step: int | None,
        phase_text: str,
        findings: list[ResearchStepResult],
    ) -> str:
        lines = [
            "# 研究进行中",
            "",
            f"- 当前阶段：{phase_text}",
            f"- 已完成步骤：{completed_steps}/{len(plan)}",
            "",
            "## 原始问题",
            "",
            query,
            "",
            "## 子任务状态",
            "",
        ]
        for index, step in enumerate(plan, start=1):
            if index <= completed_steps:
                marker = "[x]"
                status = "已完成"
            elif active_step == index:
                marker = "[-]"
                status = "进行中"
            else:
                marker = "[ ]"
                status = "等待中"
            lines.append(f"{marker} {index}. {step.title}：{status}")
            lines.append(f"   - 目标：{step.objective}")
            lines.append(f"   - 检索词：{' / '.join(step.search_queries[:2])}")

        if findings:
            lines.extend(["", "## 已获取证据", ""])
            for item in findings:
                lines.append(f"### {item.step.title}")
                lines.extend(item.findings[:3])
                if item.sources:
                    lines.append("来源：")
                    for source in item.sources[:2]:
                        lines.append(f"- [{source['title']}]({source['url']})")
        return "\n".join(lines)

    async def _run_step(self, *, query: str, step: ResearchPlanStep) -> ResearchStepResult:
        gathered_sources: list[dict] = []
        seen_urls: set[str] = set()
        for search_query in step.search_queries:
            results = await self.search_service.search(search_query)
            for item in results:
                url = str(item.get("url", "")).strip()
                dedupe_key = url or f"{search_query}:{item.get('title', '')}"
                if dedupe_key in seen_urls:
                    continue
                seen_urls.add(dedupe_key)
                excerpt = ""
                if url and "serper.dev" not in url:
                    excerpt = await self.web_fetch_service.fetch_text(url)
                gathered_sources.append(
                    {
                        "title": item.get("title", "Untitled result"),
                        "url": url,
                        "snippet": item.get("snippet", ""),
                        "excerpt": excerpt[:1200],
                        "domain": _extract_domain(url),
                        "search_query": search_query,
                    }
                )
                if len(gathered_sources) >= 4:
                    break
            if len(gathered_sources) >= 4:
                break

        findings = []
        for source in gathered_sources:
            evidence = _extract_relevant_evidence(
                source.get("excerpt") or source.get("snippet") or "",
                query=query,
                step=step,
            )
            domain = source.get("domain") or "unknown"
            findings.append(f"- {source['title']}（{domain}）：{evidence}")

        if not findings:
            findings.append("- 当前子问题没有拿到足够有效证据，建议后续补更具体的检索词或站点定向搜索。")

        return ResearchStepResult(step=step, sources=gathered_sources, findings=findings)

    async def _synthesize_report(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
    ) -> str:
        llm_report = await self._synthesize_with_llm(query=query, plan=plan, findings=findings, references=references)
        if llm_report:
            return _ensure_reference_section(llm_report, references)
        return _render_fallback_report(query=query, plan=plan, findings=findings, references=references)

    async def _synthesize_with_llm(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
    ) -> str | None:
        if self.chat_provider is None:
            self._log("llm.skip_missing_provider")
            return None

        provider_name = self.chat_provider.__class__.__name__
        provider_model = str(getattr(self.chat_provider, "model", "") or "")
        self._log(
            "llm.start",
            provider=provider_name,
            model=provider_model,
            api_key_configured=bool(getattr(self.chat_provider, "api_key", None)),
            findings_count=len(findings),
            references_count=len(references),
        )

        compact_findings = []
        for item in findings:
            compact_findings.append(f"## {item.step.title}")
            compact_findings.append(f"目标：{item.step.objective}")
            compact_findings.extend(item.findings[:4])
            for source in item.sources[:3]:
                compact_findings.append(
                    f"来源：{source['title']} | {source['url']} | 摘要：{(source.get('snippet') or '')[:180]}"
                )
                excerpt = str(source.get("excerpt", "")).strip()
                if excerpt:
                    compact_findings.append(f"正文摘录：{excerpt[:260]}")

        prompt = (
            "你是一名严谨的研究代理。请仅基于给定证据，用中文输出结构化 Markdown 报告。"
            "不要编造来源。需要包含以下标题："
            "## 执行摘要、## 研究拆解、## 关键发现、## 方案对比、## 推荐方案、## 风险与未决问题、## 参考来源。"
            "如果证据不足，要明确写出不确定性。"
        )
        user_message = "\n\n".join(
            [
                f"研究主题：{query}",
                "研究计划：\n" + "\n".join(f"- {step.title}：{step.objective}" for step in plan),
                "研究证据：\n" + "\n".join(compact_findings),
                "参考链接：\n" + "\n".join(
                    f"- {item.get('title', 'Untitled')}: {item.get('url', '')}" for item in references[:10]
                ),
            ]
        )
        try:
            reply = await asyncio.wait_for(
                self.chat_provider.chat(system_prompt=prompt, user_message=user_message),
                timeout=self.SYNTHESIS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self._log(
                "llm.timeout",
                provider=provider_name,
                model=provider_model,
                timeout_seconds=self.SYNTHESIS_TIMEOUT_SECONDS,
            )
            return None
        except TimeoutError:
            self._log(
                "llm.timeout",
                provider=provider_name,
                model=provider_model,
                timeout_seconds=self.SYNTHESIS_TIMEOUT_SECONDS,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            self._log(
                "llm.error",
                provider=provider_name,
                model=provider_model,
                error=str(exc)[:1000],
            )
            return None

        normalized_reply = reply.strip()
        if not normalized_reply:
            self._log("llm.empty", provider=provider_name, model=provider_model)
            return None
        if _looks_like_provider_failure(normalized_reply):
            self._log(
                "llm.provider_failure",
                provider=provider_name,
                model=provider_model,
                preview=normalized_reply[:300],
            )
            return None
        self._log(
            "llm.done",
            provider=provider_name,
            model=provider_model,
            reply_length=len(normalized_reply),
        )
        return normalized_reply

    def _log(self, event: str, **fields: Any) -> None:
        if self.log_callback is None:
            return
        try:
            self.log_callback(event, fields)
        except Exception:  # noqa: BLE001
            return


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def _extract_relevant_evidence(text: str, *, query: str, step: ResearchPlanStep) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return "该来源只返回了很少的公开摘要，暂时无法抽出更完整的正文证据。"

    sentences = re.split(r"(?<=[。！？.!?])\s+|(?<=;)\s+|(?<=；)\s+", cleaned)
    keywords = _keyword_set(query, step)
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        snippet = sentence.strip()
        if len(snippet) < 24:
            continue
        score = sum(1 for keyword in keywords if keyword and keyword.lower() in snippet.lower())
        scored.append((score, snippet))
    scored.sort(key=lambda item: (-item[0], -len(item[1])))
    best = [snippet for score, snippet in scored if snippet][:2]
    if not best:
        best = [cleaned[:260]]
    summary = " ".join(best)
    return summary[:260]


def _keyword_set(query: str, step: ResearchPlanStep) -> set[str]:
    raw = f"{query} {step.title} {step.objective}"
    parts = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fa5]{2,8}", raw)
    blacklist = {"实现", "方案", "当前", "研究", "问题", "目标", "步骤", "路径"}
    return {part for part in parts if part not in blacklist}


def _render_fallback_report(
    *,
    query: str,
    plan: list[ResearchPlanStep],
    findings: list[ResearchStepResult],
    references: list[dict],
) -> str:
    unique_references = _dedupe_references(references)
    lines = [
        "# 研究报告",
        "",
        "## 执行摘要",
        "",
        "这次研究已经实际执行了检索、网页正文抽取与证据整理，下面给出针对主题的收敛结论和推荐路线。",
        "",
        "## 原始问题",
        "",
        query,
        "",
        "## 研究拆解",
        "",
    ]
    for index, step in enumerate(plan, start=1):
        lines.append(f"{index}. {step.title}")
        lines.append(f"   - 目标：{step.objective}")
        lines.append(f"   - 检索词：{' / '.join(step.search_queries[:2])}")

    lines.extend(["", "## 关键发现", ""])
    for item in findings:
        lines.append(f"### {item.step.title}")
        lines.extend(item.findings[:4])

    lines.extend(
        [
            "",
            "## 方案对比",
            "",
            "- 轻量闭环路径：优先保证能在 Cloudflare Worker 内稳定跑通检索、存储和结果展示，适合面试演示与快速上线。",
            "- 深化研究路径：进一步把网页搜索、阅读压缩、证据评分和多轮规划做得更强，Agent 感知会更明显，但复杂度更高。",
            "- 体验增强路径：把研究过程可视化、增加阶段性状态与引用卡片，能明显提升用户感知，但前提是后端真正在执行研究。",
            "",
            "## 推荐方案",
            "",
            "- 优先采用“独立 research agent + 搜索服务 + 网页抓取 + 最终汇总器”的结构，把研究链路从普通聊天里拆出去。",
            "- 在 Worker 场景下，先保证任务拆解、搜索、抓取、汇总四步真实发生，再逐步引入更复杂的多代理协作。",
            "- 前端要同时展示聊天区的思考态和研究面板的进度态，避免用户误以为系统只返回了一段模板话术。",
            "",
            "## 风险与未决问题",
            "",
            "- 搜索 API 未配置时，研究会退化成占位结果，线上演示前需要确认 SERPER_API_KEY 可用。",
            "- 网页正文抓取会受站点反爬、超时和页面结构影响，需要接受部分来源只能拿到 snippet 的现实。",
            "- 如果后续要进一步增强稳定性，建议把 research job 做成更 durable 的执行链，而不是完全依赖单次请求后的内存任务。",
            "",
            "## 参考来源",
            "",
        ]
    )
    for source in unique_references[:12]:
        lines.append(f"- [{source.get('title', 'Untitled result')}]({source.get('url', '')})")
    return "\n".join(lines)


def _dedupe_references(references: list[dict]) -> list[dict]:
    unique: list[dict] = []
    seen: set[str] = set()
    for item in references:
        url = str(item.get("url", "")).strip()
        key = url or f"{item.get('title', '')}:{item.get('search_query', '')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _ensure_reference_section(markdown: str, references: list[dict]) -> str:
    if "## 参考来源" in markdown:
        return markdown
    lines = [markdown.rstrip(), "", "## 参考来源", ""]
    for item in _dedupe_references(references)[:12]:
        lines.append(f"- [{item.get('title', 'Untitled result')}]({item.get('url', '')})")
    return "\n".join(lines)


def _looks_like_provider_failure(reply: str) -> bool:
    lowered = reply.strip().lower()
    return lowered.startswith("openrouter provider is not configured") or lowered.startswith(
        "openrouter request failed"
    )
