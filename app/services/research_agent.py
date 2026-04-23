from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    strategy_id: str = "general_web"
    allowed_domains: list[str] = field(default_factory=list)
    tool_scope: list[str] = field(default_factory=lambda: ["search", "fetch"])
    model_tier: str = "default"
    max_sources: int = 4


@dataclass(slots=True)
class ResearchPlan:
    profile: str
    profile_label: str
    rationale: str
    steps: list[ResearchPlanStep]


@dataclass(slots=True)
class ResearchStepResult:
    step: ResearchPlanStep
    sources: list[dict]
    findings: list[str]
    summary: str = ""
    confidence: str = "medium"
    gaps: list[str] = field(default_factory=list)


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
        research_plan = self.build_research_plan(query)
        findings: list[ResearchStepResult] = []
        references: list[dict] = []

        await on_progress(
            "planning",
            self.render_progress_markdown(
                query=query,
                plan=research_plan.steps,
                completed_steps=0,
                active_step=1,
                phase_text="正在拆解研究问题与检索路径",
                findings=findings,
                profile_label=research_plan.profile_label,
            ),
        )

        for index, step in enumerate(research_plan.steps, start=1):
            await on_progress(
                "searching",
                self.render_progress_markdown(
                    query=query,
                    plan=research_plan.steps,
                    completed_steps=index - 1,
                    active_step=index,
                    phase_text=f"正在执行子代理：{step.title}",
                    findings=findings,
                    profile_label=research_plan.profile_label,
                ),
            )
            step_result = await self._run_step(query=query, step=step)
            findings.append(step_result)
            references.extend(step_result.sources)

        await on_progress(
            "synthesizing",
            self.render_progress_markdown(
                query=query,
                plan=research_plan.steps,
                completed_steps=len(research_plan.steps),
                active_step=None,
                phase_text="正在汇总关键发现并生成结构化报告",
                findings=findings,
                profile_label=research_plan.profile_label,
            ),
        )
        return await self._synthesize_report(
            query=query,
            plan=research_plan.steps,
            findings=findings,
            references=references,
            profile_label=research_plan.profile_label,
        )

    def build_plan(self, query: str) -> list[ResearchPlanStep]:
        return self.build_research_plan(query).steps

    def build_research_plan(self, query: str) -> ResearchPlan:
        normalized = query.strip()
        profile = _classify_profile(normalized)
        if profile == "technical_survey":
            return ResearchPlan(
                profile=profile,
                profile_label="技术调研",
                rationale="问题包含方案、架构、记忆、Agent 或实现取舍等技术关键词，适合走方案比较型研究。",
                steps=_technical_steps(normalized),
            )
        if profile == "current_events":
            return ResearchPlan(
                profile=profile,
                profile_label="时效动态",
                rationale="问题关注最近比赛、新闻、赛程或动态，核心是时间窗和多来源交叉验证。",
                steps=_current_event_steps(normalized),
            )
        if profile == "social_public_figure":
            return ResearchPlan(
                profile=profile,
                profile_label="公众人物动态",
                rationale="问题围绕公众人物近期公开发言或社交动态，需要优先二手可引用报道并控制不确定性。",
                steps=_social_figure_steps(normalized),
            )
        return ResearchPlan(
            profile="mixed",
            profile_label="混合调研",
            rationale="问题同时含有多类信号，先做分类拆解，再分别收集证据。",
            steps=_mixed_steps(normalized),
        )

    async def execute_step(self, *, query: str, step: ResearchPlanStep) -> ResearchStepResult:
        return await self._run_step(query=query, step=step)

    async def synthesize_report(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
        profile_label: str | None = None,
    ) -> str:
        return await self._synthesize_report(
            query=query,
            plan=plan,
            findings=findings,
            references=references,
            profile_label=profile_label,
        )

    def render_fallback_report(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
        profile_label: str | None = None,
    ) -> str:
        return _render_fallback_report(
            query=query,
            plan=plan,
            findings=findings,
            references=references,
            profile_label=profile_label,
        )

    def render_progress_markdown(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        completed_steps: int,
        active_step: int | None,
        phase_text: str,
        findings: list[ResearchStepResult],
        profile_label: str | None = None,
        sub_runs: list[dict[str, Any]] | None = None,
    ) -> str:
        lines = [
            "# 研究进行中",
            "",
            f"- 调研类型：{profile_label or '通用研究'}",
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
        if sub_runs:
            for item in sub_runs:
                search_queries = item.get("search_queries", [])[:2]
                lines.append(f"- {item.get('title', '未命名子任务')}：{_sub_run_status_label(item.get('status'))}")
                lines.append(f"  - 目标：{item.get('objective', '')}")
                if search_queries:
                    lines.append(f"  - 检索词：{' / '.join(search_queries)}")
        else:
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
        candidates: list[dict] = []
        seen_urls: set[str] = set()
        preferred_domains = {item.lower() for item in step.allowed_domains}
        preferred: list[dict] = []
        fallback: list[dict] = []

        for search_query in step.search_queries:
            results = await self.search_service.search(search_query, limit=step.max_sources)
            for item in results:
                url = str(item.get("url", "")).strip()
                dedupe_key = url or f"{search_query}:{item.get('title', '')}"
                if dedupe_key in seen_urls:
                    continue
                seen_urls.add(dedupe_key)
                excerpt = ""
                if url and bool(item.get("is_live_result", True)):
                    excerpt = await self.web_fetch_service.fetch_text(url)
                domain = _extract_domain(url)
                source = {
                    "title": item.get("title", "Untitled result"),
                    "url": url,
                    "snippet": item.get("snippet", ""),
                    "excerpt": excerpt[:1200],
                    "domain": domain,
                    "search_query": search_query,
                    "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "source_tier": _source_tier(domain, preferred_domains),
                    "quote_span": _extract_relevant_evidence(
                        excerpt or item.get("snippet", ""),
                        query=query,
                        step=step,
                    ),
                }
                if preferred_domains and _domain_matches(domain, preferred_domains):
                    preferred.append(source)
                else:
                    fallback.append(source)
                candidates = preferred + fallback
                if len(candidates) >= step.max_sources:
                    break
            if len(preferred) + len(fallback) >= step.max_sources:
                break

        gathered_sources = (preferred + fallback)[: step.max_sources]
        findings: list[str] = []
        for source in gathered_sources:
            domain = source.get("domain") or "unknown"
            findings.append(f"- {source['title']}（{domain}）：{source.get('quote_span') or source.get('snippet') or '暂无更完整证据。'}")

        confidence = "high" if len(gathered_sources) >= 3 else "medium" if gathered_sources else "low"
        gaps: list[str] = []
        if not findings:
            findings.append("- 当前子问题没有拿到足够有效证据，建议后续补更具体的检索词或站点定向搜索。")
            gaps.append("公开网页证据不足")
        summary = findings[0].removeprefix("- ").strip() if findings else "暂无结论"
        return ResearchStepResult(
            step=step,
            sources=gathered_sources,
            findings=findings,
            summary=summary,
            confidence=confidence,
            gaps=gaps,
        )

    async def _synthesize_report(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
        profile_label: str | None = None,
    ) -> str:
        llm_report = await self._synthesize_with_llm(
            query=query,
            plan=plan,
            findings=findings,
            references=references,
            profile_label=profile_label,
        )
        if llm_report:
            return _ensure_reference_section(llm_report, references)
        return _render_fallback_report(
            query=query,
            plan=plan,
            findings=findings,
            references=references,
            profile_label=profile_label,
        )

    async def _synthesize_with_llm(
        self,
        *,
        query: str,
        plan: list[ResearchPlanStep],
        findings: list[ResearchStepResult],
        references: list[dict],
        profile_label: str | None = None,
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

        compact_findings: list[str] = []
        for item in findings:
            compact_findings.append(f"## {item.step.title}")
            compact_findings.append(f"目标：{item.step.objective}")
            compact_findings.append(f"置信度：{item.confidence}")
            compact_findings.extend(item.findings[:4])
            for source in item.sources[:3]:
                compact_findings.append(
                    f"来源：{source['title']} | {source['url']} | source_tier={source.get('source_tier', 'web')}"
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
                f"调研类型：{profile_label or '通用研究'}",
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
            self._log("llm.timeout", provider=provider_name, model=provider_model, timeout_seconds=self.SYNTHESIS_TIMEOUT_SECONDS)
            return None
        except TimeoutError:
            self._log("llm.timeout", provider=provider_name, model=provider_model, timeout_seconds=self.SYNTHESIS_TIMEOUT_SECONDS)
            return None
        except Exception as exc:  # noqa: BLE001
            self._log("llm.error", provider=provider_name, model=provider_model, error=str(exc)[:1000])
            return None

        normalized_reply = reply.strip()
        if not normalized_reply:
            self._log("llm.empty", provider=provider_name, model=provider_model)
            return None
        if _looks_like_provider_failure(normalized_reply):
            self._log("llm.provider_failure", provider=provider_name, model=provider_model, preview=normalized_reply[:300])
            return None
        self._log("llm.done", provider=provider_name, model=provider_model, reply_length=len(normalized_reply))
        return normalized_reply

    def _log(self, event: str, **fields: Any) -> None:
        if self.log_callback is None:
            return
        try:
            self.log_callback(event, fields)
        except Exception:  # noqa: BLE001
            return


def _technical_steps(query: str) -> list[ResearchPlanStep]:
    steps = [
        ResearchPlanStep(
            title="界定技术问题与目标",
            objective="明确目标系统、成功标准与评价维度。",
            search_queries=[query, f"{query} goals scope evaluation criteria"],
            strategy_id="technical_scope",
        ),
        ResearchPlanStep(
            title="收集候选方案",
            objective="整理官方文档、开源实现与工程实践里的主流方案。",
            search_queries=[f"{query} implementation architecture", f"{query} best practices open source"],
            strategy_id="technical_sources",
        ),
        ResearchPlanStep(
            title="验证约束与边界",
            objective="核对运行时、存储、成本与依赖边界。",
            search_queries=[f"{query} runtime limits constraints", f"{query} tradeoffs cost comparison"],
            strategy_id="technical_constraints",
        ),
        ResearchPlanStep(
            title="形成建议与落地顺序",
            objective="给出推荐路线、风险和分阶段实施顺序。",
            search_queries=[f"{query} recommendation roadmap", f"{query} implementation checklist"],
            strategy_id="technical_recommendation",
        ),
    ]
    lowered = query.lower()
    if "cloudflare" in lowered or "worker" in lowered:
        steps.insert(
            2,
            ResearchPlanStep(
                title="核对 Cloudflare 相关能力",
                objective="确认 Worker、D1、R2、Queue 等组件组合方式及限制。",
                search_queries=[f"{query} Cloudflare Workers D1 R2 Queue", f"{query} Cloudflare limitations"],
                strategy_id="technical_cloudflare",
                allowed_domains=["developers.cloudflare.com"],
            ),
        )
    return steps


def _current_event_steps(query: str) -> list[ResearchPlanStep]:
    return [
        ResearchPlanStep(
            title="梳理最近时间线",
            objective="确定最近比赛、新闻或动态的时间顺序与关键节点。",
            search_queries=[f"{query} latest timeline", f"{query} recent news latest"],
            strategy_id="events_timeline",
            allowed_domains=["reuters.com", "apnews.com", "bbc.com", "espn.com"],
        ),
        ResearchPlanStep(
            title="交叉验证关键事实",
            objective="用至少两类来源核对时间、结果、比分或事件结论。",
            search_queries=[f"{query} score result latest", f"{query} official latest update"],
            strategy_id="events_verify",
            allowed_domains=["espn.com", "bbc.com", "reuters.com", "apnews.com"],
        ),
        ResearchPlanStep(
            title="补充背景与影响",
            objective="整理伤病、排名、争议或后续影响，避免只停留在单条快讯。",
            search_queries=[f"{query} impact analysis latest", f"{query} context background recent"],
            strategy_id="events_context",
        ),
    ]


def _social_figure_steps(query: str) -> list[ResearchPlanStep]:
    return [
        ResearchPlanStep(
            title="收集可引用公开动态",
            objective="优先收集主流媒体、官方声明和公开采访中的近期动态。",
            search_queries=[f"{query} latest statements interviews", f"{query} reported posts recent"],
            strategy_id="social_media_reports",
            allowed_domains=["reuters.com", "apnews.com", "theverge.com", "techcrunch.com"],
        ),
        ResearchPlanStep(
            title="核对争议与出处",
            objective="验证二手报道是否引用了一手出处，并标记不能直接确认的内容。",
            search_queries=[f"{query} fact check latest", f"{query} source verification recent"],
            strategy_id="social_verify",
            allowed_domains=["reuters.com", "apnews.com"],
        ),
        ResearchPlanStep(
            title="总结可确认结论",
            objective="只输出能明确引用来源的动态、观点与未决问题。",
            search_queries=[f"{query} summary recent reporting", f"{query} latest coverage roundup"],
            strategy_id="social_summary",
        ),
    ]


def _mixed_steps(query: str) -> list[ResearchPlanStep]:
    return [
        ResearchPlanStep(
            title="拆分混合主题",
            objective="先把问题拆成技术、时效动态或公众人物三个角度里的主轴。",
            search_queries=[query, f"{query} key aspects breakdown"],
            strategy_id="mixed_scope",
        ),
        ResearchPlanStep(
            title="收集技术与事实证据",
            objective="并行收集技术方案和实时动态两类证据，避免混为一谈。",
            search_queries=[f"{query} implementation architecture", f"{query} latest news updates"],
            strategy_id="mixed_evidence",
        ),
        ResearchPlanStep(
            title="形成综合建议",
            objective="将不同类型证据归并为一致结论并明确不确定性。",
            search_queries=[f"{query} comparison summary", f"{query} recommendation latest"],
            strategy_id="mixed_synthesis",
        ),
    ]


def _classify_profile(query: str) -> str:
    lowered = query.lower()
    scores = {
        "technical_survey": 0,
        "current_events": 0,
        "social_public_figure": 0,
    }
    technical_keywords = ("agent", "memory", "架构", "方案", "设计", "实现", "对比", "tradeoff", "rag", "worker")
    events_keywords = ("最近", "最新", "比赛", "赛程", "动态", "新闻", "近况", "recent", "latest", "match", "score")
    social_keywords = ("推特", "twitter", "x.com", "x ", "发文", "帖子", "马斯克", "musk", "tweet", "post")
    for keyword in technical_keywords:
        if keyword in lowered or keyword in query:
            scores["technical_survey"] += 1
    for keyword in events_keywords:
        if keyword in lowered or keyword in query:
            scores["current_events"] += 1
    for keyword in social_keywords:
        if keyword in lowered or keyword in query:
            scores["social_public_figure"] += 1
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_name, top_score = ranked[0]
    second_score = ranked[1][1]
    if top_score == 0 or (top_score > 0 and second_score > 0):
        return "mixed"
    return top_name


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def _domain_matches(domain: str, preferred_domains: set[str]) -> bool:
    normalized = domain.lower().strip()
    if not normalized:
        return False
    return any(normalized == item or normalized.endswith(f".{item}") for item in preferred_domains)


def _source_tier(domain: str, preferred_domains: set[str]) -> str:
    if _domain_matches(domain, preferred_domains):
        return "preferred"
    if domain.endswith(".gov") or domain.endswith(".edu") or "official" in domain:
        return "official"
    return "web"


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
    blacklist = {"实现", "方案", "当前", "研究", "问题", "目标", "步骤", "路径", "最近", "最新"}
    return {part for part in parts if part not in blacklist}


def _render_fallback_report(
    *,
    query: str,
    plan: list[ResearchPlanStep],
    findings: list[ResearchStepResult],
    references: list[dict],
    profile_label: str | None = None,
) -> str:
    unique_references = _dedupe_references(references)
    lines = [
        "# 研究报告",
        "",
        "## 执行摘要",
        "",
        f"这次研究采用“{profile_label or '通用研究'}”策略，已经实际执行了子任务拆解、检索、网页正文抽取与证据整理。",
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
            "- 通用聊天路径：只返回一次性答案，速度快，但中间证据和执行状态不可追踪。",
            "- 分型子代理路径：先按调研类型规划，再让各子任务独立执行，结果更可解释，也更接近真实研究工作流。",
            "- 重型多代理路径：并行度和可扩展性更强，但模型成本、队列复杂度和状态管理难度更高。",
            "",
            "## 推荐方案",
            "",
            "- 保持“父 orchestrator + 子 run + 最终汇总”的骨架，让每个子任务都有独立状态与结果产物。",
            "- 先把 research_profile 驱动的 plan 模板稳定下来，再逐步扩展更细的 connector 与域名白名单。",
            "- 对外展示时优先强调子任务状态、证据来源和最终引用，减少模板感。",
            "",
            "## 风险与未决问题",
            "",
            "- 搜索 API 未配置时，研究会退化成占位结果，线上演示前需要确认 SERPER_API_KEY 可用。",
            "- 网页正文抓取会受站点反爬、超时和页面结构影响，需要接受部分来源只能拿到 snippet 的现实。",
            "- 社交平台类研究若没有官方 API，应该明确告诉用户结论来自二手报道而不是平台原文。",
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
    return lowered.startswith("openrouter provider is not configured") or lowered.startswith("openrouter request failed")


def _sub_run_status_label(status: Any) -> str:
    labels = {
        "queued": "等待中",
        "running": "执行中",
        "completed": "已完成",
        "failed": "失败",
        "skipped": "已跳过",
    }
    return labels.get(str(status), str(status))
