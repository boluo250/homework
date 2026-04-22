from __future__ import annotations

import json
import re

from app.core.context import ConversationContextManager
from app.core.intents import identify_intent
from app.core.models import ChatRequest, ChatResponse, Intent, ToolResult
from app.core.prompts import build_system_prompt
from app.core.task_protocol import TaskToolAction, parse_task_tool_call
from app.providers.llm_base import ChatProviderBase
from app.services.d1_repo import AppRepository
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.services.search_service import SearchService


class AssistantAgent:
    def __init__(
        self,
        repository: AppRepository,
        chat_provider: ChatProviderBase,
        search_service: SearchService,
        rag_service: RagService,
        memory_service: MemoryService | None = None,
        context_manager: ConversationContextManager | None = None,
    ) -> None:
        self.repository = repository
        self.chat_provider = chat_provider
        self.search_service = search_service
        self.rag_service = rag_service
        self.memory_service = memory_service
        self.context_manager = context_manager or ConversationContextManager()

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        user = await self.repository.get_or_create_user(request.client_id)
        settings = await self.repository.get_or_create_assistant_settings(user.id)
        conversation = await self.repository.get_or_create_conversation(user.id, request.conversation_id)
        profile_was_incomplete = user.needs_profile_completion
        user_message_record = await self.repository.add_message(conversation.id, "user", request.message)
        if self.memory_service is not None:
            await self.memory_service.store_message(
                user_id=user.id,
                conversation_id=conversation.id,
                message_id=user_message_record.id,
                role="user",
                content=request.message,
            )

        self._maybe_extract_profile_updates(request.message)
        bot_name_updated = False
        if extracted_email := _extract_email(request.message):
            user = await self.repository.update_user_profile(user.id, email=extracted_email)
        if extracted_name := _extract_name(request.message, allow_standalone=not bool(user.name)):
            user = await self.repository.update_user_profile(user.id, name=extracted_name)
        if bot_name := _extract_bot_name(request.message):
            settings = await self.repository.update_assistant_name(user.id, bot_name)
            bot_name_updated = True

        intent = identify_intent(request.message, file_ids=request.file_ids)
        tool_results: list[ToolResult] = []

        messages = await self.repository.list_messages(conversation.id)
        summary = await self.repository.get_summary(conversation.id)
        context_bundle = self.context_manager.build(messages, summary)
        if context_bundle.should_refresh_summary and context_bundle.summary_text:
            await self.repository.save_summary(
                conversation.id,
                context_bundle.summary_text,
                context_bundle.source_message_count,
            )

        profile_completed_this_turn = profile_was_incomplete and not user.needs_profile_completion

        if user.needs_profile_completion:
            reply = self._build_profile_completion_reply(user, settings.bot_name)
        elif profile_completed_this_turn or intent == Intent.COLLECT_USER_PROFILE:
            reply = self._build_profile_saved_reply(user, settings.bot_name, bot_name_updated=bot_name_updated)
        elif intent == Intent.TASK_CRUD:
            reply, tool_results = await self._handle_task_intent(user.id, request.message)
        elif intent == Intent.SEARCH_WEB:
            results = await self.search_service.search(request.message)
            tool_results = [ToolResult(name="search_web", ok=True, content=results)]
            bullets = "\n".join(f"- {item['title']}: {item['snippet']}" for item in results)
            reply = f"我先帮你整理了搜索结果：\n{bullets}"
        elif intent == Intent.DEEP_RESEARCH:
            plan = self._build_research_plan(request.message)
            tool_results = [
                ToolResult(name="deep_research_plan", ok=True, content=plan),
                ToolResult(name="deep_research_job", ok=True, content={"mode": "async"}),
            ]
            reply = (
                "我已经开始真正执行这次研究了：会先拆题，再做网页检索、正文阅读和结论汇总。"
                "下方研究结果区会持续刷新进度，这里先把研究计划同步给你：\n"
                + "\n".join(f"- {item}" for item in plan)
            )
        elif intent == Intent.FILE_QA:
            reply, tool_results = await self._handle_file_qa(
                user_id=user.id,
                message=request.message,
                file_ids=request.file_ids,
            )
        else:
            semantic_memories = await self._load_semantic_memories(user.id, request.message)
            prompt = build_system_prompt(
                intent,
                user,
                assistant_name=settings.bot_name,
                summary=context_bundle.summary_text,
                recent_messages=context_bundle.recent_lines,
                semantic_memories=semantic_memories,
            )
            reply = await self.chat_provider.chat(system_prompt=prompt, user_message=request.message)
            if user.needs_profile_completion and intent != Intent.COLLECT_USER_PROFILE:
                missing = []
                if not user.name:
                    missing.append("名字")
                if not user.email:
                    missing.append("邮箱")
                reply = f"{reply}\n\n顺便告诉我你的{'和'.join(missing)}，我后面就能更准确地记住你。"

        assistant_message_record = await self.repository.add_message(conversation.id, "assistant", reply)
        if self.memory_service is not None:
            await self.memory_service.store_message(
                user_id=user.id,
                conversation_id=conversation.id,
                message_id=assistant_message_record.id,
                role="assistant",
                content=reply,
            )
        return ChatResponse(
            reply=reply,
            intent=intent,
            conversation_id=conversation.id,
            tool_results=tool_results,
            user_profile=user,
            assistant_name=settings.bot_name,
        )

    async def get_session_meta(self, client_id: str) -> dict:
        user = await self.repository.get_or_create_user(client_id)
        settings = await self.repository.get_or_create_assistant_settings(user.id)
        return {
            "user_profile": user,
            "assistant_name": settings.bot_name,
        }

    async def _handle_file_qa(
        self,
        *,
        user_id: str,
        message: str,
        file_ids: list[str] | None,
    ) -> tuple[str, list[ToolResult]]:
        self._log_file_qa(
            "start",
            user_id=user_id,
            message=message,
            file_ids=file_ids or [],
        )
        rag_hits = await self.rag_service.retrieve(
            user_id=user_id,
            query=message,
            file_ids=file_ids,
            limit=6,
        )
        self._log_file_qa(
            "retrieved",
            user_id=user_id,
            hit_count=len(rag_hits),
            hit_files=[hit.get("payload", {}).get("filename", "unknown") for hit in rag_hits],
            file_ids=file_ids or [],
        )
        tool_results = [ToolResult(name="file_qa", ok=True, content=rag_hits)]
        if not rag_hits:
            self._log_file_qa("empty_hits", user_id=user_id, file_ids=file_ids or [])
            return "文件问答链路已经接好接口，但当前还没有可用的向量检索结果。", tool_results

        all_files = await self.repository.list_files(user_id)
        selected_files = [item for item in all_files if not file_ids or item.id in file_ids]
        self._log_file_qa(
            "selected_files",
            user_id=user_id,
            selected_count=len(selected_files),
            selected_files=[item.filename for item in selected_files],
        )
        file_descriptions = []
        for item in selected_files[:3]:
            summary = (item.summary or "").strip()
            file_descriptions.append(f"- {item.filename}: {summary[:180] if summary else '暂无摘要'}")

        evidence_blocks = []
        total_chars = 0
        question_mode = _infer_document_qa_mode(message)
        full_document_context = await self._build_selected_document_context(
            user_id=user_id,
            selected_files=selected_files,
            question_mode=question_mode,
        )
        for index, hit in enumerate(rag_hits, start=1):
            snippet = str(hit.get("text", "")).strip()
            if not snippet:
                continue
            snippet = re.sub(r"\n{3,}", "\n\n", snippet)
            snippet = snippet[:900]
            block = (
                f"[片段 {index}] "
                f"filename={hit.get('payload', {}).get('filename', 'unknown')} "
                f"chunk_index={hit.get('payload', {}).get('chunk_index', 'n/a')} "
                f"score={float(hit.get('score', 0.0)):.3f}\n{snippet}"
            )
            if total_chars + len(block) > 5000 and evidence_blocks:
                break
            evidence_blocks.append(block)
            total_chars += len(block)

        system_prompt = "\n\n".join(
            [
                "You are a file question-answering assistant.",
                "Use the retrieved snippets as evidence, but do not dump them back verbatim unless the user explicitly asks for quotes.",
                "Tailor the response style to the user's question: summarize when asked for a summary, compare when asked for comparison, answer directly when asked a specific question, and extract structured facts when the user asks for fields or items.",
                "When the user asks to introduce, summarize, analyze, or review one or more documents, synthesize the answer into clear Chinese instead of listing raw snippets.",
                "Prefer clear structure: direct answer first, then key evidence or key points, then a short conclusion when helpful.",
                "If the evidence is partial or conflicting, say so explicitly.",
                "Do not stop mid-sentence. Produce a complete answer.",
                "If full document context is available, use it to improve completeness. If only partial retrieved evidence is available, say that the answer is based on partial context.",
                "Available file summaries:\n" + ("\n".join(file_descriptions) if file_descriptions else "- 暂无文件摘要"),
                "Full document context:\n" + (full_document_context or "未提供全文上下文"),
                "Retrieved evidence:\n" + "\n\n".join(evidence_blocks),
            ]
        )
        user_prompt = (
            f"用户问题：{message}\n\n"
            + _build_document_qa_instruction(question_mode)
        )
        self._log_file_qa(
            "model_call.start",
            user_id=user_id,
            question_mode=question_mode,
            evidence_count=len(evidence_blocks),
            selected_count=len(selected_files),
            system_prompt_chars=len(system_prompt),
            user_prompt_chars=len(user_prompt),
        )
        try:
            reply = await self.chat_provider.chat(system_prompt=system_prompt, user_message=user_prompt)
        except Exception as exc:
            self._log_file_qa(
                "model_call.error",
                user_id=user_id,
                error=str(exc),
            )
            raise
        self._log_file_qa(
            "model_call.done",
            user_id=user_id,
            reply_chars=len(reply),
        )
        self._log_file_qa(
            "model_reply",
            user_id=user_id,
            preview=reply[:240],
            provider_failure=self._looks_like_provider_failure(reply),
        )
        if self._looks_like_provider_failure(reply):
            reply = self._fallback_file_qa_reply(message, rag_hits)
        reply = self._append_file_citations(reply, rag_hits)
        return reply, tool_results

    async def _build_selected_document_context(
        self,
        *,
        user_id: str,
        selected_files: list,
        question_mode: str,
    ) -> str:
        if not selected_files or len(selected_files) > 2:
            return ""
        if question_mode not in {"summary", "overview", "compare"}:
            return ""

        sections: list[str] = []
        total_chars = 0
        for item in selected_files:
            chunks = await self.rag_service.qdrant_store.list_chunks_by_file(user_id=user_id, file_id=item.id, limit=24)
            if not chunks:
                continue

            ordered_parts = []
            for chunk in chunks:
                payload = chunk.get("payload", {})
                text = str(payload.get("text", "")).strip()
                if not text:
                    continue
                if total_chars + len(text) > 12000 and sections:
                    break
                ordered_parts.append(text)
                total_chars += len(text)
            if ordered_parts:
                sections.append(f"[文档] {item.filename}\n" + "\n\n".join(ordered_parts))
            if total_chars >= 12000:
                break
        return "\n\n".join(sections).strip()

    async def _handle_task_intent(self, user_id: str, message: str) -> tuple[str, list[ToolResult]]:
        call = parse_task_tool_call(message)
        if call.action == TaskToolAction.CREATE:
            task = await self.repository.create_task(
                user_id,
                title=call.title or "未命名任务",
                details=call.details or "",
                priority=call.priority,
                due_at=call.due_at,
            )
            details_suffix = f"，需求：{task.details}" if task.details else ""
            return (
                f"已创建任务：{task.title}，优先级 {task.priority.value}，状态 {task.status.value}{details_suffix}。",
                [ToolResult(name=call.action.value, ok=True, content=task.to_dict())],
            )
        if call.action == TaskToolAction.UPDATE:
            task = await self.repository.update_task(
                user_id,
                title_hint=call.title or message,
                details=call.details,
                status=call.status,
                priority=call.priority,
                due_at=call.due_at,
            )
            if not task:
                return (
                    "我没找到要更新的任务。你可以把任务名放进引号里再试一次。",
                    [ToolResult(name=call.action.value, ok=False, content=call.to_dict())],
                )
            details_suffix = f"，需求：{task.details}" if task.details else ""
            return (
                f"任务已更新：{task.title}，状态 {task.status.value}，优先级 {task.priority.value}{details_suffix}。",
                [ToolResult(name=call.action.value, ok=True, content=task.to_dict())],
            )
        if call.action == TaskToolAction.DELETE:
            deleted = await self.repository.delete_task(user_id, title_hint=call.title)
            if not deleted:
                return (
                    "我没有找到匹配的任务，暂时无法删除。",
                    [ToolResult(name=call.action.value, ok=False, content=call.to_dict())],
                )
            return (
                f"已删除任务：{call.title or '目标任务'}。",
                [ToolResult(name=call.action.value, ok=True, content=call.to_dict())],
            )
        tasks = await self.repository.list_tasks(user_id)
        if not tasks:
            return (
                "你现在还没有任务，我可以直接帮你创建一个。",
                [ToolResult(name=call.action.value, ok=True, content=[])],
            )
        lines = [
            f"- {task.title} | status={task.status.value} | priority={task.priority.value} | due={task.due_at or 'n/a'}"
            + (f" | details={task.details}" if task.details else "")
            for task in tasks
        ]
        return (
            "当前任务如下：\n" + "\n".join(lines),
            [ToolResult(name=call.action.value, ok=True, content=[task.to_dict() for task in tasks])],
        )

    def _build_research_plan(self, message: str) -> list[str]:
        return [
            f"明确研究目标：{message}",
            "拆分 3 到 5 个子问题并定义各自的证据来源",
            "对子问题执行搜索、阅读和摘要压缩",
            "汇总成结构化 Markdown 报告并给出推荐结论",
        ]

    def _maybe_extract_profile_updates(self, message: str) -> None:
        _ = message

    def _build_profile_completion_reply(self, user, assistant_name: str) -> str:
        missing = []
        if not user.name:
            missing.append("名字")
        if not user.email:
            missing.append("邮箱")

        if user.name and not user.email:
            return (
                f"我已经记住你叫 {user.name} 了。接下来还需要你的邮箱，"
                f"这样 {assistant_name} 后面才能稳定记住并称呼你。"
            )
        if user.email and not user.name:
            return (
                f"我已经记住你的邮箱 {user.email}。接下来告诉我你的名字，"
                f"这样 {assistant_name} 后面就能直接称呼你。"
            )
        return f"开始之前，先告诉我你的{'和'.join(missing)}，我会先记下来。"

    def _build_profile_saved_reply(self, user, assistant_name: str, *, bot_name_updated: bool) -> str:
        parts = [f"好的，我记住了。你是 {user.name}，邮箱是 {user.email}。"]
        if bot_name_updated:
            parts.append(f"以后你可以叫我 {assistant_name}。")
        else:
            parts.append(f"后面我会直接称呼你为 {user.name}。")
        return " ".join(parts)

    async def _load_semantic_memories(self, user_id: str, query: str) -> list[str]:
        if self.memory_service is None:
            return []
        memory_hits = await self.memory_service.retrieve_memories(user_id=user_id, query=query, limit=4)
        lines = []
        for hit in memory_hits:
            text = str(hit.get("text", "")).strip()
            if not text:
                continue
            role = hit.get("payload", {}).get("role", "memory")
            lines.append(f"- {role}: {text[:180]}")
        return lines

    def _append_file_citations(self, reply: str, rag_hits: list[dict]) -> str:
        citations: list[str] = []
        seen: set[tuple[str, int]] = set()
        for hit in rag_hits[:4]:
            payload = hit.get("payload", {})
            filename = str(payload.get("filename", "unknown"))
            chunk_index = int(payload.get("chunk_index", 0))
            key = (filename, chunk_index)
            if key in seen:
                continue
            seen.add(key)
            citations.append(f"- {filename}#片段{chunk_index}")
        if not citations:
            return reply
        return reply.rstrip() + "\n\n参考来源：\n" + "\n".join(citations)

    def _looks_like_provider_failure(self, reply: str) -> bool:
        lowered = reply.strip().lower()
        return lowered.startswith("openrouter provider is not configured") or lowered.startswith(
            "openrouter request failed"
        )

    def _fallback_file_qa_reply(self, message: str, rag_hits: list[dict]) -> str:
        snippets = []
        for hit in rag_hits[:4]:
            snippet = str(hit.get("text", "")).strip()
            if not snippet:
                continue
            compact = re.sub(r"\s+", " ", snippet)
            snippets.append(compact[:220])
        if not snippets:
            return "我暂时没有从文件里提取到足够证据，没法可靠回答这个问题。"
        if _infer_document_qa_mode(message) in {"summary", "overview"}:
            lines = [
                "我先根据已检索到的文件内容做一个简要总结：",
                "",
                "1. 这份材料的核心内容主要集中在以下几点：",
            ]
            lines.extend(f"- {item}" for item in snippets[:3])
            lines.append("")
            lines.append("如果你愿意，我可以继续把它整理成更完整的文档摘要、问答卡片或结构化要点。")
            return "\n".join(lines)
        return "我从文件中检索到的关键信息有：\n" + "\n".join(f"- {item}" for item in snippets)

    def _log_file_qa(self, event: str, **fields) -> None:
        payload = {"scope": "file_qa", "event": event, **fields}
        try:
            print(f"[taskmate] {json.dumps(payload, ensure_ascii=False, default=str)}")
        except Exception:  # noqa: BLE001
            print(f"[taskmate] file_qa event={event} fields={fields!r}")


def _extract_name(message: str, *, allow_standalone: bool = False) -> str | None:
    patterns = [
        r"我叫([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"我的名字是([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
    ]
    for pattern in patterns:
        matched = re.search(pattern, message)
        if matched:
            return matched.group(1).strip()
    if allow_standalone:
        return _extract_standalone_name(message)
    return None


def _extract_email(message: str) -> str | None:
    matched = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", message)
    if matched:
        return matched.group(1)
    return None


def _extract_bot_name(message: str) -> str | None:
    patterns = [
        r"叫你([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"你的名字改成([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
    ]
    for pattern in patterns:
        matched = re.search(pattern, message)
        if matched:
            return matched.group(1).strip()
    return None


def _extract_standalone_name(message: str) -> str | None:
    candidate = re.sub(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", " ", message)
    candidate = re.sub(r"(我叫|我的名字是|邮箱是|邮箱|email|叫你|昵称|名字)", " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ，。,:：")
    if not candidate:
        return None

    disallowed_keywords = (
        "任务",
        "创建",
        "新增",
        "删除",
        "更新",
        "修改",
        "研究",
        "调研",
        "搜索",
        "上传",
        "文件",
        "帮我",
        "需要",
        "要求",
        "请",
    )
    if any(keyword in candidate for keyword in disallowed_keywords):
        return None
    if re.fullmatch(r"[A-Za-z\u4e00-\u9fa5·\s]{2,20}", candidate):
        return candidate.strip()
    return None


def _infer_document_qa_mode(message: str) -> str:
    lowered = message.lower()
    if any(keyword in lowered for keyword in ["对比", "比较", "区别", "compare", "comparison", "vs"]):
        return "compare"
    if any(keyword in lowered for keyword in ["提取", "列出", "清单", "字段", "表格", "extract", "list", "fields"]):
        return "extract"
    if any(
        keyword in lowered
        for keyword in ["介绍", "总结", "概括", "归纳", "评价", "分析", "介绍下", "summarize", "summary", "introduce", "overview", "analyze", "review"]
    ):
        return "summary"
    if any(keyword in lowered for keyword in ["是什么", "为什么", "如何", "多少", "who", "what", "why", "how"]):
        return "qa"
    return "overview"


def _build_document_qa_instruction(question_mode: str) -> str:
    common = "请基于上面的文件证据直接回答。不要只摘抄原文，要先理解再表达。"
    if question_mode == "summary":
        return (
            common
            + "这是总结类问题，请先给出整体概括，再整理关键要点，并补一句结论或判断。"
        )
    if question_mode == "compare":
        return (
            common
            + "这是对比类问题，请先给出总体结论，再按维度比较相同点、不同点和适用场景。"
        )
    if question_mode == "extract":
        return (
            common
            + "这是信息抽取类问题，请按清单或小标题输出，尽量结构化，缺失项明确标注。"
        )
    if question_mode == "qa":
        return (
            common
            + "这是具体问答，请先直接回答，再补充对应证据或依据。"
        )
    return (
        common
        + "这是文档介绍/综述类问题，请优先输出完整且通顺的说明，再补充关键点。"
    )
