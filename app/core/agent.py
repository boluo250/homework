from __future__ import annotations

import json
import re
from typing import Any

from app.core.intent_interpreter import IntentInterpretation, LLMIntentInterpreter
from app.services.file_service import MEDIA_INGEST_STAGING_PREFIX
from app.core.models import ChatRequest, ChatResponse, Intent, TaskPriority, TaskStatus, ToolResult
from app.core.task_protocol import TaskToolAction, is_generic_task_reference
from app.providers.llm_base import ChatProviderBase, ToolCall, ToolDefinition
from app.runtime.prompt_builder import build_chat_system_prompt, build_file_qa_prompt_bundle, build_tool_router_prompt
from app.runtime.session_context import ConversationContextManager
from app.runtime.skills_loader import SkillsLoader
from app.runtime.tool_registry import ToolRegistry
from app.services.d1_repo import AppRepository
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.services.search_service import SearchService
from app.state.assistant_state import AssistantState
from app.state.task_state import TaskState
from app.state.user_state import UserState
from app.tools.assistant_identity_tool import AssistantIdentityTool
from app.tools.file_qa_citations import append_file_citations, extract_answer_and_used_evidence_ids
from app.tools.profile_tool import ProfileTool
from app.tools.rag_tool import RagTool
from app.tools.research_tool import ResearchTool
from app.tools.task_tool import TaskTool


class AssistantAgent:
    def __init__(
        self,
        repository: AppRepository,
        chat_provider: ChatProviderBase,
        search_service: SearchService,
        rag_service: RagService,
        memory_service: MemoryService | None = None,
        context_manager: ConversationContextManager | None = None,
        profile_tool: ProfileTool | None = None,
        assistant_identity_tool: AssistantIdentityTool | None = None,
        task_tool: TaskTool | None = None,
        rag_tool: RagTool | None = None,
        research_tool: ResearchTool | None = None,
        tool_registry: ToolRegistry | None = None,
        skills_loader: SkillsLoader | None = None,
    ) -> None:
        self.repository = repository
        self.chat_provider = chat_provider
        self.search_service = search_service
        self.rag_service = rag_service
        self.memory_service = memory_service
        self.context_manager = context_manager or ConversationContextManager()
        self.intent_interpreter = LLMIntentInterpreter(chat_provider)
        self.user_state = UserState(repository)
        self.assistant_state = AssistantState(repository)
        self.task_state = TaskState(repository)
        self.profile_tool = profile_tool or ProfileTool(self.user_state)
        self.assistant_identity_tool = assistant_identity_tool or AssistantIdentityTool(self.assistant_state)
        self.task_tool = task_tool or TaskTool(self.task_state)
        self.rag_tool = rag_tool
        self.research_tool = research_tool or ResearchTool(None)
        self.tool_registry = tool_registry or ToolRegistry()
        self.skills_loader = skills_loader or SkillsLoader()

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

        messages = await self.repository.list_messages(conversation.id)
        summary = await self.repository.get_summary(conversation.id)
        context_bundle = self.context_manager.build(messages, summary)
        if context_bundle.should_refresh_summary and context_bundle.summary_text:
            await self.repository.save_summary(
                conversation.id,
                context_bundle.summary_text,
                context_bundle.source_message_count,
            )

        tasks = await self.repository.list_tasks(user.id)
        if self.chat_provider.supports_tool_calls():
            outcome = await self._handle_tool_routed_turn(
                request=request,
                user=user,
                settings=settings,
                context_bundle=context_bundle,
                tasks=tasks,
                profile_was_incomplete=profile_was_incomplete,
            )
        else:
            outcome = await self._handle_interpreted_turn(
                request=request,
                user=user,
                settings=settings,
                context_bundle=context_bundle,
                tasks=tasks,
                profile_was_incomplete=profile_was_incomplete,
            )

        user = outcome["user"]
        settings = outcome["settings"]
        intent = outcome["intent"]
        tool_results = outcome["tool_results"]
        reply = outcome["reply"]

        reply = self._personalize_reply(reply, user.name, intent=intent)

        assistant_message_record = await self.repository.add_message(
            conversation.id,
            "assistant",
            reply,
            tool_calls_json=json.dumps([item.to_dict() for item in tool_results], ensure_ascii=False) if tool_results else None,
        )
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

    async def _handle_tool_routed_turn(
        self,
        *,
        request: ChatRequest,
        user,
        settings,
        context_bundle,
        tasks: list,
        profile_was_incomplete: bool,
    ) -> dict[str, Any]:
        tool_response = await self.chat_provider.chat_with_tools(
            system_prompt=self._build_tool_router_prompt(
                user=user,
                assistant_name=settings.bot_name,
                summary=context_bundle.summary_text,
                recent_messages=context_bundle.recent_lines,
                tasks=tasks,
                message=request.message,
                file_ids=request.file_ids,
            ),
            user_message=request.message,
            tools=self._build_business_tools(file_ids=request.file_ids),
        )

        if self._looks_like_provider_failure(tool_response.content or ""):
            return await self._handle_interpreted_turn(
                request=request,
                user=user,
                settings=settings,
                context_bundle=context_bundle,
                tasks=tasks,
                profile_was_incomplete=profile_was_incomplete,
            )

        if not tool_response.tool_calls:
            if tool_response.content:
                return {
                    "intent": Intent.GENERAL_CHAT,
                    "reply": tool_response.content,
                    "tool_results": [],
                    "user": user,
                    "settings": settings,
                }
            return await self._handle_interpreted_turn(
                request=request,
                user=user,
                settings=settings,
                context_bundle=context_bundle,
                tasks=tasks,
                profile_was_incomplete=profile_was_incomplete,
            )

        primary_intent = Intent.GENERAL_CHAT
        tool_results: list[ToolResult] = []
        reply_parts: list[str] = []
        ordered_calls = self._order_tool_calls(tool_response.tool_calls)
        bot_name_updated = False

        for tool_call in ordered_calls:
            tool_name = tool_call.name
            args = tool_call.arguments or {}

            if tool_name == "save_profile":
                name = _clean_tool_text(args.get("name"))
                email = _clean_tool_email(args.get("email"))
                if name or email:
                    user = await self.profile_tool.set(user.id, name=name, email=email)
                    tool_results.append(
                        ToolResult(
                            name="save_profile",
                            ok=True,
                            content={"name": user.name, "email": user.email},
                        )
                    )
                    primary_intent = self._merge_primary_intent(primary_intent, Intent.COLLECT_USER_PROFILE)
                else:
                    tool_results.append(ToolResult(name="save_profile", ok=False, content={"reason": "missing_profile_fields"}))
                continue

            if tool_name == "recall_profile":
                field = _normalize_profile_field(args.get("field"))
                reply_parts.append(await self.profile_tool.get(user, field))
                tool_results.append(ToolResult(name="recall_profile", ok=True, content={"field": field}))
                primary_intent = self._merge_primary_intent(primary_intent, Intent.COLLECT_USER_PROFILE)
                continue

            if tool_name == "rename_assistant":
                assistant_name = _clean_tool_text(args.get("assistant_name"))
                if assistant_name:
                    settings = await self.assistant_identity_tool.set(user.id, assistant_name)
                    bot_name_updated = True
                    reply_parts.append(f"以后你可以叫我 {settings.bot_name}。")
                    tool_results.append(
                        ToolResult(
                            name="rename_assistant",
                            ok=True,
                            content={"assistant_name": settings.bot_name},
                        )
                    )
                    primary_intent = self._merge_primary_intent(primary_intent, Intent.COLLECT_USER_PROFILE)
                else:
                    tool_results.append(ToolResult(name="rename_assistant", ok=False, content={"reason": "missing_assistant_name"}))
                continue

            if tool_name == "get_assistant_name":
                settings = await self.assistant_identity_tool.get(user.id)
                reply_parts.append(f"你现在叫我 {settings.bot_name}。")
                tool_results.append(ToolResult(name="get_assistant_name", ok=True, content={"assistant_name": settings.bot_name}))
                continue

            if tool_name in {
                TaskToolAction.CREATE.value,
                TaskToolAction.UPDATE.value,
                TaskToolAction.DELETE.value,
                TaskToolAction.GET.value,
                TaskToolAction.LIST.value,
            }:
                task_reply, task_tool_results, primary_intent = await self._execute_routed_task_call(
                    user_id=user.id,
                    message=request.message,
                    tool_name=tool_name,
                    args=args,
                    current_intent=primary_intent,
                    user=user,
                    assistant_name=settings.bot_name,
                )
                reply_parts.append(task_reply)
                tool_results.extend(task_tool_results)
                continue

            if tool_name == "search_web":
                query = _clean_tool_text(args.get("query")) or request.message
                results = await self.search_service.search(query)
                tool_results.append(ToolResult(name="search_web", ok=True, content=results))
                primary_intent = self._merge_primary_intent(primary_intent, Intent.SEARCH_WEB)
                if results:
                    bullets = "\n".join(f"- {item['title']}: {item['snippet']}" for item in results)
                    reply_parts.append(f"我先帮你整理了搜索结果：\n{bullets}")
                else:
                    reply_parts.append("我先帮你查了，但现在还没有拿到可用搜索结果。")
                continue

            if tool_name == "start_research":
                query = _clean_tool_text(args.get("query")) or request.message
                plan = self.research_tool.build_plan(query)
                tool_results.extend(
                    [
                        ToolResult(name="deep_research_plan", ok=True, content=plan),
                        ToolResult(name="deep_research_job", ok=True, content={"mode": "async", "query": query}),
                    ]
                )
                primary_intent = self._merge_primary_intent(primary_intent, Intent.DEEP_RESEARCH)
                reply_parts.append(
                    "我已经开始真正执行这次研究了：会先拆题，再做网页检索、正文阅读和结论汇总。"
                    "下方研究结果区会持续刷新进度，这里先把研究计划同步给你：\n"
                    + "\n".join(f"- {item}" for item in plan)
                )
                continue

            if tool_name == "answer_file_question":
                file_ids = _clean_tool_file_ids(args.get("file_ids")) or request.file_ids
                question = _clean_tool_text(args.get("question")) or request.message
                file_outcome = await self._handle_file_qa(user_id=user.id, message=question, file_ids=file_ids)
                tool_results.extend(file_outcome[1])
                reply_parts.append(file_outcome[0])
                primary_intent = self._merge_primary_intent(primary_intent, Intent.FILE_QA)
                continue

            if tool_name == "list_uploaded_files":
                inv_reply, inv_results = await self._list_uploaded_files_reply(user_id=user.id)
                tool_results.extend(inv_results)
                reply_parts.append(inv_reply)
                primary_intent = self._merge_primary_intent(primary_intent, Intent.FILE_QA)
                continue

            tool_results.append(ToolResult(name=tool_name, ok=False, content={"reason": "unknown_tool"}))

        if not reply_parts:
            if profile_was_incomplete and not user.needs_profile_completion:
                reply_parts.append(self.profile_tool.build_saved_reply(user, settings.bot_name, bot_name_updated=bot_name_updated))
                primary_intent = self._merge_primary_intent(primary_intent, Intent.COLLECT_USER_PROFILE)
            elif tool_response.content:
                reply_parts.append(tool_response.content)
            else:
                return await self._handle_interpreted_turn(
                    request=request,
                    user=user,
                    settings=settings,
                    context_bundle=context_bundle,
                    tasks=tasks,
                    profile_was_incomplete=profile_was_incomplete,
                )
        elif profile_was_incomplete and not user.needs_profile_completion and not any(
            "我记住了" in part or "你是" in part for part in reply_parts
        ):
            reply_parts.insert(0, self.profile_tool.build_saved_reply(user, settings.bot_name, bot_name_updated=bot_name_updated))
            primary_intent = self._merge_primary_intent(primary_intent, Intent.COLLECT_USER_PROFILE)

        return {
            "intent": primary_intent,
            "reply": "\n\n".join(part for part in reply_parts if part.strip()),
            "tool_results": tool_results,
            "user": user,
            "settings": settings,
        }

    async def _handle_interpreted_turn(
        self,
        *,
        request: ChatRequest,
        user,
        settings,
        context_bundle,
        tasks: list,
        profile_was_incomplete: bool,
    ) -> dict[str, Any]:
        interpretation = await self.intent_interpreter.interpret(
            message=request.message,
            user=user,
            assistant_name=settings.bot_name,
            recent_lines=context_bundle.recent_lines,
            tasks=tasks,
            file_ids=request.file_ids,
        )

        bot_name_updated = False
        if interpretation.write_profile and (interpretation.user_name or interpretation.user_email):
            user = await self.profile_tool.set(
                user.id,
                name=interpretation.user_name if interpretation.user_name else None,
                email=interpretation.user_email if interpretation.user_email else None,
            )
        if interpretation.rename_assistant and interpretation.assistant_name:
            settings = await self.assistant_identity_tool.set(user.id, interpretation.assistant_name)
            bot_name_updated = True

        intent = interpretation.primary_intent
        tool_results: list[ToolResult] = []

        should_gate_for_profile = (
            user.needs_profile_completion
            and not interpretation.profile_query_field
            and not interpretation.assistant_query
            and intent not in {Intent.FILE_QA, Intent.DEEP_RESEARCH}
        )

        if should_gate_for_profile:
            reply = self.profile_tool.build_completion_reply(user, settings.bot_name)
        elif interpretation.profile_query_field:
            reply = await self.profile_tool.get(user, interpretation.profile_query_field)
        elif interpretation.assistant_query:
            reply = f"你现在叫我 {settings.bot_name}。"
        elif intent == Intent.COLLECT_USER_PROFILE and (interpretation.write_profile or interpretation.rename_assistant):
            reply = self.profile_tool.build_saved_reply(user, settings.bot_name, bot_name_updated=bot_name_updated)
        elif interpretation.needs_clarification and interpretation.clarification_prompt:
            reply = interpretation.clarification_prompt
        elif intent == Intent.TASK_CRUD:
            reply, tool_results = await self._handle_task_intent(user.id, interpretation)
        elif intent == Intent.SEARCH_WEB:
            results = await self.search_service.search(request.message)
            tool_results = [ToolResult(name="search_web", ok=True, content=results)]
            bullets = "\n".join(f"- {item['title']}: {item['snippet']}" for item in results)
            reply = f"我先帮你整理了搜索结果：\n{bullets}"
        elif intent == Intent.DEEP_RESEARCH:
            plan = self.research_tool.build_plan(request.message)
            tool_results = [
                ToolResult(name="deep_research_plan", ok=True, content=plan),
                ToolResult(name="deep_research_job", ok=True, content={"mode": "async"}),
            ]
            reply = (
                "我已经开始真正执行这次研究了：会先拆题，再做网页检索、正文阅读和结论汇总。"
                "下方研究结果区会持续刷新进度，这里先把研究计划同步给你：\n"
                + "\n".join(f"- {item}" for item in plan)
            )
        elif intent == Intent.FILE_QA and interpretation.file_action == "inventory":
            reply, tool_results = await self._list_uploaded_files_reply(user_id=user.id)
        elif intent == Intent.FILE_QA:
            reply, tool_results = await self._handle_file_qa(
                user_id=user.id,
                message=request.message,
                file_ids=request.file_ids,
                answer_mode=interpretation.file_answer_mode,
            )
        else:
            semantic_memories = await self._load_semantic_memories(user.id, request.message)
            prompt = build_chat_system_prompt(
                intent,
                user,
                assistant_name=settings.bot_name,
                summary=context_bundle.summary_text,
                recent_messages=context_bundle.recent_lines,
                semantic_memories=semantic_memories,
                skill_instructions=self.skills_loader.render_router_instructions(
                    message=request.message,
                    file_ids=request.file_ids,
                ),
            )
            reply = await self.chat_provider.chat(system_prompt=prompt, user_message=request.message)
            if user.needs_profile_completion and intent != Intent.COLLECT_USER_PROFILE:
                missing = []
                if not user.name:
                    missing.append("名字")
                if not user.email:
                    missing.append("邮箱")
                reply = f"{reply}\n\n顺便告诉我你的{'和'.join(missing)}，我后面就能更准确地记住你。"

        return {
            "intent": intent,
            "reply": reply,
            "tool_results": tool_results,
            "user": user,
            "settings": settings,
        }

    def _build_tool_router_prompt(
        self,
        *,
        user,
        assistant_name: str,
        summary: str | None,
        recent_messages: list[str],
        tasks: list,
        message: str,
        file_ids: list[str],
    ) -> str:
        return build_tool_router_prompt(
            user=user,
            assistant_name=assistant_name,
            summary=summary,
            recent_messages=recent_messages,
            tasks=tasks,
            file_ids=file_ids,
            skill_instructions=self.skills_loader.render_router_instructions(message=message, file_ids=file_ids),
        )

    def _build_business_tools(self, *, file_ids: list[str]) -> list[ToolDefinition]:
        return self.tool_registry.build_business_tools(file_ids=file_ids)

    def _order_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolCall]:
        return self.tool_registry.order_tool_calls(tool_calls)

    async def _execute_routed_task_call(
        self,
        *,
        user_id: str,
        message: str,
        tool_name: str,
        args: dict[str, Any],
        current_intent: Intent,
        user,
        assistant_name: str,
    ) -> tuple[str, list[ToolResult], Intent]:
        if user.needs_profile_completion:
            return (
                self.profile_tool.build_completion_reply(user, assistant_name),
                [ToolResult(name=tool_name, ok=False, content={"reason": "profile_incomplete"})],
                self._merge_primary_intent(current_intent, Intent.TASK_CRUD),
            )

        title = _normalize_tool_task_title(args.get("title"))
        target_ref = _normalize_tool_target_ref(args.get("target_ref"), raw_title=_clean_tool_text(args.get("title")))
        interpretation = IntentInterpretation(
            primary_intent=Intent.TASK_CRUD,
            task_action=TaskToolAction(tool_name),
            should_execute=True,
            task_title=title,
            task_details=_clean_tool_text(args.get("details")),
            task_priority=_parse_tool_priority(args.get("priority")),
            task_due_at=_clean_tool_text(args.get("due_at")),
            task_status=_parse_tool_status(args.get("status")),
            target_ref=target_ref,
        )
        if interpretation.task_action == TaskToolAction.CREATE and not interpretation.task_title:
            return (
                "可以，我先帮你建任务。这个任务想叫什么？",
                [ToolResult(name=tool_name, ok=False, content={"reason": "missing_task_title", "raw_message": message})],
                self._merge_primary_intent(current_intent, Intent.TASK_CRUD),
            )

        reply, task_tool_results = await self._handle_task_intent(user_id, interpretation)
        return reply, task_tool_results, self._merge_primary_intent(current_intent, Intent.TASK_CRUD)

    def _merge_primary_intent(self, current: Intent, incoming: Intent) -> Intent:
        order = {
            Intent.GENERAL_CHAT: 0,
            Intent.COLLECT_USER_PROFILE: 1,
            Intent.SEARCH_WEB: 2,
            Intent.TASK_CRUD: 3,
            Intent.FILE_QA: 4,
            Intent.DEEP_RESEARCH: 5,
        }
        return incoming if order[incoming] >= order[current] else current

    async def _list_uploaded_files_reply(self, *, user_id: str) -> tuple[str, list[ToolResult]]:
        if self.rag_tool is None:
            return (
                "当前对话环境未接入文件索引服务，无法列出已上传文档。",
                [ToolResult(name="list_uploaded_files", ok=False, content={"reason": "rag_tool_unavailable"})],
            )
        files = await self.rag_tool.list_files(user_id)
        tool_results = [ToolResult(name="list_uploaded_files", ok=True, content={"files": files})]
        if not files:
            return (
                "你当前账号下还没有任何已上传并入库的文档。上传成功后我会写入元数据与向量索引，之后你就可以让我列出清单或直接提问。",
                tool_results,
            )
        lines: list[str] = ["这是你账号下已保存、可检索的文档清单（来自持久化存储，不限于本次会话中勾选的文件）："]
        for item in files[:40]:
            fn = str(item.get("filename", "unknown"))
            fid = str(item.get("id", ""))
            vc = int(item.get("vector_count") or 0)
            hint = _file_ingest_hint_for_list(summary=item.get("summary"), vector_count=vc)
            lines.append(f"- {fn}（file_id={fid}，已向量化片段约 {vc} 条{hint}）")
        if len(files) > 40:
            lines.append(f"... 共 {len(files)} 份，此处仅列出前 40 份。")
        return ("\n".join(lines), tool_results)

    async def _handle_file_qa(
        self,
        *,
        user_id: str,
        message: str,
        file_ids: list[str] | None,
        answer_mode: str | None = None,
    ) -> tuple[str, list[ToolResult]]:
        if self.rag_tool is not None:
            outcome = await self.rag_tool.answer(
                user_id=user_id,
                message=message,
                file_ids=file_ids,
                answer_mode=answer_mode,
            )
            return outcome.reply, outcome.tool_results
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
        question_mode = answer_mode or _infer_document_qa_mode(message)
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

        system_prompt, user_prompt = build_file_qa_prompt_bundle(
            question=message,
            question_mode=question_mode,
            file_descriptions=file_descriptions,
            full_document_context=full_document_context,
            evidence_blocks=evidence_blocks,
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
        used_evidence_ids: list[int] = []
        if self._looks_like_provider_failure(reply):
            reply = self._fallback_file_qa_reply(message, rag_hits)
            used_evidence_ids = list(range(1, min(len(rag_hits), 4) + 1))
        else:
            reply, used_evidence_ids = extract_answer_and_used_evidence_ids(reply, evidence_count=len(evidence_blocks))
        reply = append_file_citations(reply, rag_hits, used_evidence_ids=used_evidence_ids)
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

    async def _handle_task_intent(
        self,
        user_id: str,
        interpretation: IntentInterpretation,
    ) -> tuple[str, list[ToolResult]]:
        outcome = await self.task_tool.execute(
            user_id,
            action=interpretation.task_action or TaskToolAction.LIST,
            task_title=interpretation.task_title,
            task_details=interpretation.task_details,
            task_status=interpretation.task_status,
            task_priority=interpretation.task_priority,
            task_due_at=interpretation.task_due_at,
            target_ref=interpretation.target_ref,
        )
        return outcome.reply, outcome.tool_results

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

    def _build_profile_recall_reply(self, user, field: str) -> str:
        if field == "email":
            if user.email:
                return f"我记得你的邮箱是 {user.email}。"
            return "我现在还不知道你的邮箱，你可以直接告诉我。"
        if field == "profile":
            known_bits = []
            if user.name:
                known_bits.append(f"名字是 {user.name}")
            if user.email:
                known_bits.append(f"邮箱是 {user.email}")
            if known_bits:
                return "我现在记得你的资料：" + "，".join(known_bits) + "。"
            return "我现在还没有记住你的资料。你可以先告诉我名字和邮箱。"
        if user.name:
            return f"我记得你叫 {user.name}。"
        return "我现在还不知道你的名字，你可以直接告诉我。"

    async def _resolve_task_reference(
        self,
        user_id: str,
        *,
        title: str | None,
        target_ref: str | None,
    ):
        tasks = await self.repository.list_tasks(user_id)
        if title:
            task = await self.repository.find_task_by_title(user_id, title)
            if task:
                return task, None
            return None, "我没找到这个任务。你可以把任务名放进引号里再试一次。"
        if not tasks:
            return None, "你现在还没有任务，我可以直接帮你创建一个。"
        if target_ref == "recent_task":
            return self._pick_recent_task(tasks), None
        if target_ref == "single_task" or len(tasks) == 1:
            return tasks[0], None
        return None, "我找到多个任务了。你可以直接告诉我任务名，或者说“删掉刚刚创建的那个任务”。"

    def _pick_recent_task(self, tasks: list):
        return max(
            enumerate(tasks),
            key=lambda item: (
                getattr(item[1], "updated_at", "") or "",
                getattr(item[1], "created_at", "") or "",
                item[0],
            ),
        )[1]

    def _personalize_reply(self, reply: str, user_name: str | None, *, intent: Intent) -> str:
        if not user_name or intent in {Intent.COLLECT_USER_PROFILE, Intent.FILE_QA}:
            return reply
        if reply.lstrip().startswith(user_name) or user_name in reply[:80]:
            return reply
        return f"{user_name}，{reply}"

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


def _file_ingest_hint_for_list(*, summary: object, vector_count: int) -> str:
    """Aligns with FileService summary markers for async video ingest (see file_service.MEDIA_INGEST_PENDING)."""
    if vector_count > 0:
        return ""
    s = str(summary or "").strip()
    if s == "[ingest_pending]":
        return "；状态：视频/大媒体已入队，转写与向量化在 Queue 消费者中执行（未完成前为 0 条）"
    if s.startswith(MEDIA_INGEST_STAGING_PREFIX):
        return "；状态：多模态转写已完成，向量化在第二条队列任务中执行（尚未写入向量）"
    if s.startswith("[ingest_failed]"):
        body = s.removeprefix("[ingest_failed]").strip()
        short = (body[:100] + "…") if len(body) > 100 else body
        return f"；状态：转写失败（{short}）" if short else "；状态：转写失败"
    if s == "[ingest_empty]":
        return "；状态：模型返回空文本，未生成可索引片段"
    return ""


def _clean_tool_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("\"'“”").strip(" ，。,:：")
    if not cleaned or cleaned.lower() in {"null", "none", "unknown"}:
        return None
    return cleaned


def _clean_tool_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    matched = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", value)
    if matched:
        return matched.group(1)
    return None


def _normalize_profile_field(value: object) -> str:
    if isinstance(value, str) and value in {"name", "email", "profile"}:
        return value
    return "profile"


def _clean_tool_file_ids(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned or None


def _parse_tool_priority(value: object) -> TaskPriority | None:
    if not isinstance(value, str):
        return None
    try:
        return TaskPriority(value)
    except ValueError:
        return None


def _parse_tool_status(value: object) -> TaskStatus | None:
    if not isinstance(value, str):
        return None
    try:
        return TaskStatus(value)
    except ValueError:
        return None


def _normalize_tool_task_title(value: object) -> str | None:
    cleaned = _clean_tool_text(value)
    if not cleaned or len(cleaned) < 2 or is_generic_task_reference(cleaned):
        return None
    return cleaned


def _normalize_tool_target_ref(value: object, *, raw_title: str | None) -> str | None:
    if isinstance(value, str) and value in {"recent_task", "single_task", "named_task"}:
        return value
    if not raw_title:
        return None
    if any(
        token in raw_title
        for token in (
            "刚创建",
            "刚刚创建",
            "刚才创建",
            "最近",
            "最新",
            "这个任务",
            "那个任务",
            "该任务",
            "已经创建的任务",
            "已创建的任务",
            "创建的任务",
        )
    ):
        return "recent_task"
    return None


def _extract_name(message: str, *, allow_standalone: bool = False) -> str | None:
    patterns = [
        r"我叫([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"我的名字是([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"我的姓名是([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"姓名是([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"你可以叫我([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"叫我([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
    ]
    for pattern in patterns:
        matched = re.search(pattern, message)
        if matched:
            return _normalize_profile_value(matched.group(1))
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
        r"以后叫你([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"以后我叫你([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"以后你就叫([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"你的名字改成([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"把你的名字改成([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"把你的昵称改成([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"你的昵称改成([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
        r"给你起名叫([A-Za-z\u4e00-\u9fa5·\s]{2,20})",
    ]
    for pattern in patterns:
        matched = re.search(pattern, message)
        if matched:
            return _normalize_profile_value(matched.group(1))
    return None


def _extract_standalone_name(message: str) -> str | None:
    candidate = re.sub(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", " ", message)
    candidate = re.sub(
        r"(我叫|我的名字是|我的姓名是|姓名是|邮箱是|邮箱|email|叫你|叫我|你可以叫我|昵称|名字)",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
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
        return _normalize_profile_value(candidate)
    return None


def _normalize_profile_value(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip(" ，。,:：")
    normalized = re.sub(r"(吧|呀|啦|哦)$", "", normalized).strip(" ，。,:：")
    return normalized


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
