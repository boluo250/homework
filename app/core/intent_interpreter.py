from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.core.intents import FILE_KEYWORDS, RESEARCH_KEYWORDS, SEARCH_KEYWORDS, looks_like_user_task_request
from app.core.models import Intent, TaskPriority, TaskStatus, UserProfile
from app.core.task_protocol import TaskToolAction, is_generic_task_reference, parse_task_tool_call
from app.providers.llm_base import ChatProviderBase


@dataclass(slots=True)
class IntentInterpretation:
    primary_intent: Intent
    task_action: TaskToolAction | None = None
    file_action: str | None = None
    file_answer_mode: str | None = None
    should_execute: bool = False
    needs_clarification: bool = False
    clarification_prompt: str | None = None
    confidence: float = 0.0
    target_ref: str | None = None
    task_title: str | None = None
    task_new_title: str | None = None
    task_details: str | None = None
    task_priority: TaskPriority | None = None
    task_start_at: str | None = None
    task_end_at: str | None = None
    task_due_at: str | None = None
    task_status: TaskStatus | None = None
    user_name: str | None = None
    user_email: str | None = None
    assistant_name: str | None = None
    write_profile: bool = False
    rename_assistant: bool = False
    profile_query_field: str | None = None
    assistant_query: bool = False
    explanation: str | None = None


class LLMIntentInterpreter:
    def __init__(self, chat_provider: ChatProviderBase) -> None:
        self.chat_provider = chat_provider

    async def interpret(
        self,
        *,
        message: str,
        user: UserProfile,
        assistant_name: str,
        recent_lines: list[str],
        tasks: list,
        file_ids: list[str],
    ) -> IntentInterpretation:
        fallback = self._fallback_interpret(
            message=message,
            user=user,
            assistant_name=assistant_name,
            tasks=tasks,
            file_ids=file_ids,
        )
        prompt = self._build_prompt(
            message=message,
            user=user,
            assistant_name=assistant_name,
            recent_lines=recent_lines,
            tasks=tasks,
            file_ids=file_ids,
            fallback=fallback,
        )
        raw = await self.chat_provider.chat(
            system_prompt=self._system_prompt(),
            user_message=prompt,
        )
        parsed = self._parse_json(raw)
        if parsed is None:
            return fallback
        return self._merge_with_fallback(parsed, fallback)

    def _system_prompt(self) -> str:
        return (
            "You are a strict intent interpreter for a conversational task assistant, used only as a fallback router. "
            "Return JSON only. Never explain. "
            "You decide whether the user's message should execute a write action now, "
            "ask a clarification question, answer from existing profile memory, start deep research, "
            "answer against files, list uploaded files, search the web, or continue as normal chat."
        )

    def _build_prompt(
        self,
        *,
        message: str,
        user: UserProfile,
        assistant_name: str,
        recent_lines: list[str],
        tasks: list,
        file_ids: list[str],
        fallback: IntentInterpretation,
    ) -> str:
        task_titles = [task.title for task in tasks[:5]]
        payload = {
            "message": message,
            "current_user_profile": {
                "name": user.name,
                "email": user.email,
            },
            "assistant_name": assistant_name,
            "recent_conversation": recent_lines[-6:],
            "recent_task_titles": task_titles,
            "selected_file_count": len(file_ids),
            "selected_file_ids": file_ids[:3],
            "heuristic_hint": {
                "primary_intent": fallback.primary_intent.value,
                "task_action": fallback.task_action.value if fallback.task_action else None,
                "file_action": fallback.file_action,
                "file_answer_mode": fallback.file_answer_mode,
                "task_title": fallback.task_title,
                "target_ref": fallback.target_ref,
                "profile_query_field": fallback.profile_query_field,
                "assistant_query": fallback.assistant_query,
                "write_profile": fallback.write_profile,
                "rename_assistant": fallback.rename_assistant,
                "should_execute": fallback.should_execute,
                "needs_clarification": fallback.needs_clarification,
                "clarification_prompt": fallback.clarification_prompt,
            },
            "json_schema": {
                "primary_intent": "collect_user_profile | task_crud | search_web | deep_research | file_qa | general_chat",
                "task_action": "create_task | update_task | delete_task | get_task | list_tasks | null",
                "file_action": "inventory | answer | null",
                "file_answer_mode": "summary | compare | extract | qa | overview | null",
                "should_execute": "boolean",
                "needs_clarification": "boolean",
                "clarification_prompt": "string | null",
                "confidence": "number between 0 and 1",
                "target_ref": "named_task | recent_task | single_task | none | null",
                "task_title": "string | null",
                "task_new_title": "string | null",
                "task_details": "string | null",
                "task_priority": "high | medium | low | null",
                "task_start_at": "string | null",
                "task_end_at": "string | null",
                "task_due_at": "string | null",
                "task_status": "todo | in_progress | done | null",
                "user_name": "string | null",
                "user_email": "string | null",
                "assistant_name": "string | null",
                "write_profile": "boolean",
                "rename_assistant": "boolean",
                "profile_query_field": "name | email | profile | null",
                "assistant_query": "boolean",
                "explanation": "short string"
            },
            "rules": [
                "If the user is asking what name/email you already know, set profile_query_field and do not write profile.",
                "If the user asks the assistant's name or nickname, set assistant_query=true and do not rename assistant.",
                "Never extract nonsense tails like 个 or 啥么 as real entities.",
                "For task creation without a clear title, set should_execute=false and ask for the missing title.",
                "For references like 这个任务 or 刚创建的任务, prefer target_ref=recent_task instead of inventing a title.",
                "For selected-file questions, prefer primary_intent=file_qa and set file_action=answer.",
                "If the user asks to list or enumerate uploaded documents (有哪些文档/文件、上传了哪些、数据库里有什么资料), prefer primary_intent=file_qa and set file_action=inventory.",
                "If the user asks to summarize/compare/extract/answer from files, set file_answer_mode accordingly.",
                "For research requests like 调研/方案/tradeoff, prefer primary_intent=deep_research.",
                "This interpreter is conservative fallback logic. Prefer preserving the heuristic result when uncertain.",
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _parse_json(self, raw: str) -> dict | None:
        text = raw.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start : end + 1]
        try:
            payload = json.loads(text)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _merge_with_fallback(self, payload: dict, fallback: IntentInterpretation) -> IntentInterpretation:
        primary_intent = _parse_intent(payload.get("primary_intent")) or fallback.primary_intent
        task_action = _parse_task_action(payload.get("task_action")) or fallback.task_action
        task_title = _clean_optional_text(payload.get("task_title"))
        if task_title and is_generic_task_reference(task_title):
            task_title = None
        task_new_title = _clean_optional_text(payload.get("task_new_title"))
        if task_new_title and is_generic_task_reference(task_new_title):
            task_new_title = None

        interpretation = IntentInterpretation(
            primary_intent=primary_intent,
            task_action=task_action,
            file_action=_parse_file_action(payload.get("file_action")) or fallback.file_action,
            file_answer_mode=_parse_file_answer_mode(payload.get("file_answer_mode")) or fallback.file_answer_mode,
            should_execute=bool(payload.get("should_execute", fallback.should_execute)),
            needs_clarification=bool(payload.get("needs_clarification", fallback.needs_clarification)),
            clarification_prompt=_clean_optional_text(payload.get("clarification_prompt")) or fallback.clarification_prompt,
            confidence=_parse_confidence(payload.get("confidence"), fallback.confidence),
            target_ref=_clean_optional_text(payload.get("target_ref")) or fallback.target_ref,
            task_title=task_title or fallback.task_title,
            task_new_title=task_new_title or fallback.task_new_title,
            task_details=_clean_optional_text(payload.get("task_details")) or fallback.task_details,
            task_priority=_parse_priority(payload.get("task_priority")) or fallback.task_priority,
            task_start_at=_clean_optional_text(payload.get("task_start_at")) or fallback.task_start_at,
            task_end_at=_clean_optional_text(payload.get("task_end_at")) or fallback.task_end_at,
            task_due_at=_clean_optional_text(payload.get("task_due_at")) or fallback.task_due_at,
            task_status=_parse_status(payload.get("task_status")) or fallback.task_status,
            user_name=_clean_optional_text(payload.get("user_name")) or fallback.user_name,
            user_email=_parse_email(payload.get("user_email")) or fallback.user_email,
            assistant_name=_clean_optional_text(payload.get("assistant_name")) or fallback.assistant_name,
            write_profile=bool(payload.get("write_profile", fallback.write_profile)),
            rename_assistant=bool(payload.get("rename_assistant", fallback.rename_assistant)),
            profile_query_field=_clean_optional_text(payload.get("profile_query_field")) or fallback.profile_query_field,
            assistant_query=bool(payload.get("assistant_query", fallback.assistant_query)),
            explanation=_clean_optional_text(payload.get("explanation")) or fallback.explanation,
        )
        return self._normalize_interpretation(interpretation, fallback)

    def _normalize_interpretation(
        self,
        interpretation: IntentInterpretation,
        fallback: IntentInterpretation,
    ) -> IntentInterpretation:
        if interpretation.profile_query_field or interpretation.assistant_query:
            interpretation.should_execute = False
            interpretation.needs_clarification = False
        if interpretation.primary_intent == Intent.FILE_QA:
            if not interpretation.file_action:
                interpretation.file_action = fallback.file_action or "answer"
            if interpretation.file_action == "answer" and not interpretation.file_answer_mode:
                interpretation.file_answer_mode = fallback.file_answer_mode or "overview"
        if interpretation.task_action == TaskToolAction.CREATE and not interpretation.task_title:
            interpretation.should_execute = False
            interpretation.needs_clarification = True
            interpretation.clarification_prompt = interpretation.clarification_prompt or "可以，我先帮你建任务。这个任务想叫什么？"
        if interpretation.task_action == TaskToolAction.CREATE and interpretation.task_title:
            missing = _missing_task_schedule_fields(interpretation.task_start_at, interpretation.task_end_at)
            if missing:
                interpretation.should_execute = False
                interpretation.needs_clarification = True
                interpretation.clarification_prompt = _build_task_schedule_clarification(missing)
        if interpretation.task_action in {TaskToolAction.UPDATE, TaskToolAction.DELETE, TaskToolAction.GET}:
            if not interpretation.task_title and not interpretation.target_ref:
                interpretation.should_execute = False
                interpretation.needs_clarification = True
                interpretation.clarification_prompt = interpretation.clarification_prompt or "你想操作哪一个任务？可以直接告诉我任务名。"
        return interpretation

    def _fallback_interpret(
        self,
        *,
        message: str,
        user: UserProfile,
        assistant_name: str,
        tasks: list,
        file_ids: list[str],
    ) -> IntentInterpretation:
        lowered = message.lower()
        question = _looks_like_question(message)
        extracted_name = _extract_user_name(message) if not question else None
        if not extracted_name and not question and not user.name:
            extracted_name = _extract_standalone_name(message)
        extracted_email = _parse_email(message)
        extracted_bot_name = _extract_assistant_name(message) if not question else None
        task_call = parse_task_tool_call(message)
        target_ref = _detect_task_reference(message, task_call)

        if _asks_about_assistant_name(message):
            return IntentInterpretation(
                primary_intent=Intent.GENERAL_CHAT,
                assistant_query=True,
                explanation="assistant_name_query",
                confidence=0.95,
            )
        if _asks_about_profile(message):
            return IntentInterpretation(
                primary_intent=Intent.GENERAL_CHAT,
                profile_query_field=_profile_query_field(message),
                explanation="profile_query",
                confidence=0.95,
            )

        if looks_like_file_inventory(message):
            return IntentInterpretation(
                primary_intent=Intent.FILE_QA,
                file_action="inventory",
                should_execute=True,
                confidence=0.88,
                explanation="file_inventory",
            )

        if file_ids and "上传" not in message:
            return IntentInterpretation(
                primary_intent=Intent.FILE_QA,
                file_action="answer",
                file_answer_mode=infer_file_answer_mode(message),
                should_execute=True,
                confidence=0.9,
                explanation="selected_file_context",
            )

        if _matches_any(message, RESEARCH_KEYWORDS):
            return IntentInterpretation(
                primary_intent=Intent.DEEP_RESEARCH,
                should_execute=True,
                user_name=extracted_name,
                user_email=extracted_email,
                assistant_name=extracted_bot_name,
                write_profile=bool(extracted_name or extracted_email),
                rename_assistant=bool(extracted_bot_name),
                confidence=0.9,
                explanation="research_request",
            )

        if _looks_like_file_question(message):
            return IntentInterpretation(
                primary_intent=Intent.FILE_QA,
                file_action="answer",
                file_answer_mode=infer_file_answer_mode(message),
                should_execute=True,
                confidence=0.8,
                explanation="file_question",
            )

        if _matches_any(lowered, SEARCH_KEYWORDS):
            return IntentInterpretation(
                primary_intent=Intent.SEARCH_WEB,
                should_execute=True,
                confidence=0.8,
                explanation="search_request",
            )

        if extracted_name or extracted_email or extracted_bot_name:
            return IntentInterpretation(
                primary_intent=Intent.COLLECT_USER_PROFILE,
                should_execute=bool(extracted_name or extracted_email or extracted_bot_name),
                user_name=extracted_name,
                user_email=extracted_email,
                assistant_name=extracted_bot_name,
                write_profile=bool(extracted_name or extracted_email),
                rename_assistant=bool(extracted_bot_name),
                confidence=0.92,
                explanation="profile_or_nickname_update",
            )

        task_like_message = task_call.action != TaskToolAction.LIST or looks_like_user_task_request(message)
        if task_like_message:
            interpretation = IntentInterpretation(
                primary_intent=Intent.TASK_CRUD,
                task_action=task_call.action,
                task_title=task_call.title,
                task_details=task_call.details,
                task_priority=task_call.priority,
                task_start_at=task_call.start_at,
                task_end_at=task_call.end_at,
                task_due_at=task_call.due_at,
                task_status=task_call.status,
                target_ref=target_ref,
                confidence=0.82,
                explanation="task_request",
            )
            if task_call.action == TaskToolAction.CREATE:
                interpretation.should_execute = bool(task_call.title)
                interpretation.needs_clarification = not interpretation.should_execute
                if interpretation.needs_clarification:
                    interpretation.clarification_prompt = "可以，我先帮你建任务。这个任务想叫什么？"
                else:
                    missing = _missing_task_schedule_fields(task_call.start_at, task_call.end_at)
                    if missing:
                        interpretation.should_execute = False
                        interpretation.needs_clarification = True
                        interpretation.clarification_prompt = _build_task_schedule_clarification(missing)
            elif task_call.action == TaskToolAction.LIST:
                interpretation.should_execute = True
            else:
                interpretation.should_execute = bool(task_call.title or target_ref == "recent_task" or (target_ref == "single_task" and len(tasks) == 1))
                interpretation.needs_clarification = not interpretation.should_execute
                if interpretation.needs_clarification:
                    interpretation.clarification_prompt = "你想操作哪一个任务？可以直接告诉我任务名。"
            return interpretation

        return IntentInterpretation(
            primary_intent=Intent.GENERAL_CHAT,
            confidence=0.5,
            explanation="general_chat",
        )


def _parse_intent(value: object) -> Intent | None:
    if not isinstance(value, str):
        return None
    try:
        return Intent(value)
    except ValueError:
        return None


def _parse_task_action(value: object) -> TaskToolAction | None:
    if not isinstance(value, str):
        return None
    try:
        return TaskToolAction(value)
    except ValueError:
        return None


def _parse_file_action(value: object) -> str | None:
    if isinstance(value, str) and value in {"inventory", "answer"}:
        return value
    return None


def _parse_file_answer_mode(value: object) -> str | None:
    if isinstance(value, str) and value in {"summary", "compare", "extract", "qa", "overview"}:
        return value
    return None


def _parse_priority(value: object) -> TaskPriority | None:
    if not isinstance(value, str):
        return None
    try:
        return TaskPriority(value)
    except ValueError:
        return None


def _parse_status(value: object) -> TaskStatus | None:
    if not isinstance(value, str):
        return None
    try:
        return TaskStatus(value)
    except ValueError:
        return None


def _parse_confidence(value: object, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    return fallback


def _missing_task_schedule_fields(start_at: str | None, end_at: str | None) -> list[str]:
    missing: list[str] = []
    if not start_at:
        missing.append("start_at")
    if not end_at:
        missing.append("end_at")
    return missing


def _build_task_schedule_clarification(missing: list[str]) -> str:
    if missing == ["start_at", "end_at"]:
        return "可以，我先帮你建这个待办。开始日期和结束日期分别是什么？"
    if missing == ["start_at"]:
        return "可以，我先帮你建这个待办。开始日期是什么？"
    return "可以，我先帮你建这个待办。结束日期是什么？"


def _clean_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip(" \n\t，。:：")
    return cleaned or None


def _matches_any(message: str, keywords: set[str]) -> bool:
    return any(keyword in message for keyword in keywords)


def _looks_like_question(message: str) -> bool:
    return any(token in message for token in ("吗", "么", "?", "？", "知道", "记得", "是不是", "能不能"))


def _asks_about_profile(message: str) -> bool:
    return any(
        token in message
        for token in (
            "知道我叫",
            "我叫啥",
            "我叫什么",
            "我的名字",
            "记得我叫",
            "我的邮箱",
            "知道我的邮箱",
            "记得我的邮箱",
            "我的资料",
        )
    ) and _looks_like_question(message)


def _profile_query_field(message: str) -> str:
    if "邮箱" in message or "email" in message.lower():
        return "email"
    if "资料" in message:
        return "profile"
    return "name"


def _asks_about_assistant_name(message: str) -> bool:
    return any(
        token in message
        for token in (
            "你叫什么",
            "你叫啥",
            "你的名字",
            "你现在叫什么",
            "我给你起了什么名字",
            "我叫你什么",
        )
    ) and _looks_like_question(message)


def _looks_like_file_question(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in message or keyword in lowered for keyword in FILE_KEYWORDS) and "上传" not in message


def infer_file_answer_mode(message: str) -> str:
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


def looks_like_file_inventory(message: str) -> bool:
    """User wants a catalog of persisted uploads, not semantic QA over file contents."""
    lowered = message.lower()
    needles = (
        "有哪些文档",
        "有哪些文件",
        "列出文档",
        "列出文件",
        "文档列表",
        "文件列表",
        "上传了哪些",
        "我有哪些文件",
        "我有哪些文档",
        "查询数据库",
        "数据库里",
        "库里有哪些",
        "知识库",
        "indexed documents",
        "list uploaded",
        "list files",
    )
    return any(n in message or n.lower() in lowered for n in needles)


def _detect_task_reference(message: str, task_call) -> str | None:
    if task_call.title:
        return "named_task"
    if any(token in message for token in ("刚创建", "刚刚创建", "刚才创建", "这个任务", "刚刚那个任务", "那个任务", "最新任务", "最近任务")):
        return "recent_task"
    if any(token in message for token in ("已经创建的任务", "已创建的任务", "创建的任务")):
        return "recent_task"
    return None


def _extract_user_name(message: str) -> str | None:
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
            return _normalize_name(matched.group(1))
    return None


def _extract_assistant_name(message: str) -> str | None:
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
            return _normalize_name(matched.group(1))
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
        return _normalize_name(candidate)
    return None


def _parse_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    matched = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", value)
    if matched:
        return matched.group(1)
    return None


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip(" ，。,:：")
    normalized = re.sub(r"(吧|呀|啦|哦)$", "", normalized).strip(" ，。,:：")
    return normalized
