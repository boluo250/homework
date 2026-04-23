from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.models import Intent, UserProfile

FILE_QA_MODES = {"summary", "compare", "extract", "qa", "overview"}
ROUTER_BUNDLE_ID = "router.main"

BASE_SYSTEM_PROMPT = """
You are a lightweight task and research assistant running inside Cloudflare Workers.
Always be concise, accurate, and action-oriented.
Prefer structured answers when tools returned structured data.
""".strip()

RESPONSE_INTENT_PROMPTS: dict[Intent, str] = {
    Intent.COLLECT_USER_PROFILE: (
        "Help the user complete missing profile information in a natural chat flow. "
        "If name or email is missing, ask only for the missing field."
    ),
    Intent.TASK_CRUD: (
        "Interpret the user's task intent first. Prefer creating, listing, updating, "
        "deleting, or fetching tasks via tools instead of answering vaguely."
    ),
    Intent.SEARCH_WEB: (
        "Use search results when available. Mention freshness caveats if the search "
        "service is not configured."
    ),
    Intent.DEEP_RESEARCH: (
        "Break complex questions into a few sub-questions and return a markdown report "
        "with findings, tradeoffs, and a recommendation."
    ),
    Intent.FILE_QA: (
        "Use retrieved file snippets when available. Quote compactly and mention when "
        "the answer is based on partial file support."
    ),
    Intent.GENERAL_CHAT: "Be helpful and continue the conversation naturally.",
}


@dataclass(slots=True)
class PromptBundle:
    bundle_id: str
    system_prompt: str
    user_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


INTENT_BUNDLE_IDS: dict[Intent, str] = {
    Intent.COLLECT_USER_PROFILE: "intent.profile_memory",
    Intent.TASK_CRUD: "intent.task_crud",
    Intent.SEARCH_WEB: "intent.search_web",
    Intent.DEEP_RESEARCH: "intent.deep_research",
    Intent.FILE_QA: "intent.file_chat",
    Intent.GENERAL_CHAT: "intent.general_chat",
}

RESPONSE_BUNDLE_IDS: dict[Intent, str] = {
    Intent.COLLECT_USER_PROFILE: "profile_memory",
    Intent.TASK_CRUD: "task_crud",
    Intent.SEARCH_WEB: "search_web",
    Intent.DEEP_RESEARCH: "deep_research",
    Intent.FILE_QA: "file_chat",
    Intent.GENERAL_CHAT: "general_chat",
}


def build_router_prompt_bundle(
    *,
    user: UserProfile,
    assistant_name: str,
    summary: str | None,
    recent_messages: list[str],
    tasks: list,
    file_ids: list[str],
    skill_instructions: str | None = None,
) -> PromptBundle:
    task_lines = [f"- {item.title} | status={item.status.value} | priority={item.priority.value}" for item in tasks[:8]]
    recent_block = recent_messages[-6:] if recent_messages else []
    context_parts = [
        "You are the action router for a Chinese task assistant.",
        "Decide whether to answer normally or call one or more business tools.",
        "Prefer tool calls for persistent writes, task CRUD, profile recall, assistant nickname changes, deep research, web search, and selected-file QA.",
        "Important safety rules:",
        "- Never treat generic fragments like 个, 一个, 这个任务, 啥么 as a real task title or person name.",
        "- If the user asks what name/email you remember, call recall_profile instead of guessing.",
        "- If the user asks what your nickname is, call get_assistant_name.",
        "- If a task write lacks a concrete target or title, ask a short clarification in plain text and do not call the task tool yet.",
        "- If the user asks to list or query what documents/files are uploaded (e.g. 有哪些文档、数据库里有什么、上传了哪些), call list_uploaded_files. Do not claim you cannot access the database.",
        "- For file questions, distinguish inventory vs answer: list_uploaded_files is for 文档清单/有哪些文件; answer_file_question is for summarize / compare / extract / direct QA over file contents.",
        "- If selected files are relevant, prefer answer_file_question.",
        "- For research requests like 调研 / 方案 / 对比 / tradeoff, prefer start_research.",
        f"Current assistant nickname: {assistant_name}",
        f"Current user profile: name={user.name or 'unknown'}, email={user.email or 'unknown'}",
        f"Selected file ids: {file_ids or []}",
        "Recent tasks:\n" + "\n".join(task_lines or ["- 暂无任务"]),
    ]
    if summary:
        context_parts.append(f"Conversation summary:\n{summary}")
    if recent_block:
        context_parts.append("Recent conversation:\n" + "\n".join(recent_block))
    if skill_instructions:
        context_parts.append("Operational skills:\n" + skill_instructions)
    return PromptBundle(
        bundle_id=ROUTER_BUNDLE_ID,
        system_prompt="\n\n".join(context_parts),
        metadata={"kind": "router"},
    )


def build_intent_bundle(intent: Intent) -> PromptBundle:
    sections = _build_intent_bundle_sections(intent)
    return PromptBundle(
        bundle_id=INTENT_BUNDLE_IDS[intent],
        system_prompt="\n\n".join(sections) if sections else "",
        metadata={"intent": intent.value, "kind": "intent"},
    )


def build_response_prompt_bundle(
    intent: Intent,
    user: UserProfile,
    *,
    assistant_name: str,
    summary: str | None = None,
    recent_messages: list[str] | None = None,
    semantic_memories: list[str] | None = None,
    skill_instructions: str | None = None,
) -> PromptBundle:
    system_prompt = _build_base_response_system_prompt(
        intent=intent,
        user=user,
        assistant_name=assistant_name,
        summary=summary,
        recent_messages=recent_messages,
        semantic_memories=semantic_memories,
    )
    intent_bundle = build_intent_bundle(intent)
    if intent_bundle.system_prompt:
        system_prompt += "\n\n" + intent_bundle.system_prompt
    if skill_instructions:
        system_prompt += "\n\nOperational skills:\n" + skill_instructions
    return PromptBundle(
        bundle_id=f"response.{RESPONSE_BUNDLE_IDS[intent]}",
        system_prompt=system_prompt,
        metadata={"intent": intent.value, "kind": "response", "intent_bundle_id": intent_bundle.bundle_id},
    )


def build_intent_prompt_bundle(
    intent: Intent,
    user: UserProfile,
    *,
    assistant_name: str,
    summary: str | None = None,
    recent_messages: list[str] | None = None,
    semantic_memories: list[str] | None = None,
    skill_instructions: str | None = None,
) -> PromptBundle:
    return build_response_prompt_bundle(
        intent,
        user,
        assistant_name=assistant_name,
        summary=summary,
        recent_messages=recent_messages,
        semantic_memories=semantic_memories,
        skill_instructions=skill_instructions,
    )


def build_file_qa_prompt_bundle(
    *,
    question: str,
    question_mode: str,
    file_descriptions: list[str],
    full_document_context: str,
    evidence_blocks: list[str],
) -> PromptBundle:
    mode = question_mode if question_mode in FILE_QA_MODES else "overview"
    system_parts = [
        "You are a file question-answering assistant.",
        "Use the retrieved snippets as evidence, but do not dump them back verbatim unless the user explicitly asks for quotes.",
        "Answer in Chinese.",
        "If the evidence is partial or conflicting, say so explicitly.",
        "Do not stop mid-sentence. Produce a complete answer.",
        "Prefer synthesis over snippet listing unless the user explicitly asks for raw excerpts.",
        "After the prose answer, output exactly one final machine-readable line: EVIDENCE_IDS: [ids].",
        "The ids must reference the [片段 N] labels from Retrieved evidence and only include snippets you actually used.",
        "If you could not rely on any retrieved snippet, output EVIDENCE_IDS: [].",
        "Do not mention EVIDENCE_IDS anywhere else in the answer.",
        "Available file summaries:\n" + ("\n".join(file_descriptions) if file_descriptions else "- 暂无文件摘要"),
        "Full document context:\n" + (full_document_context or "未提供全文上下文"),
        "Retrieved evidence:\n" + ("\n\n".join(evidence_blocks) if evidence_blocks else "未检索到片段"),
        _build_file_qa_system_template(mode),
    ]
    user_prompt = f"用户问题：{question}\n\n" + _build_document_qa_instruction(mode)
    return PromptBundle(
        bundle_id=f"response.file_qa.{mode}",
        system_prompt="\n\n".join(system_parts),
        user_prompt=user_prompt,
        metadata={"question_mode": mode, "kind": "response"},
    )


def _build_intent_bundle_sections(intent: Intent) -> list[str]:
    if intent == Intent.TASK_CRUD:
        return [
            "## Task Bundle",
            "Treat task requests as operational work. Prefer concrete task actions or short clarifications over abstract discussion.",
        ]
    if intent == Intent.DEEP_RESEARCH:
        return [
            "## Research Bundle",
            "Frame research work as a structured investigation: sub-questions, evidence, tradeoffs, and a recommendation.",
        ]
    if intent == Intent.FILE_QA:
        return [
            "## File Bundle",
            "When files are relevant, distinguish file inventory from content QA, and prefer grounded answers over generic chat.",
        ]
    return []


def _build_base_response_system_prompt(
    *,
    intent: Intent,
    user: UserProfile,
    assistant_name: str,
    summary: str | None = None,
    recent_messages: list[str] | None = None,
    semantic_memories: list[str] | None = None,
) -> str:
    profile_line = f"User profile: name={user.name or 'unknown'}, email={user.email or 'unknown'}."
    assistant_line = f"Assistant nickname: {assistant_name}."
    addressing_line = (
        f"When replying in natural conversation, address the user as {user.name} when it feels natural."
        if user.name
        else "The user's preferred name is not known yet."
    )
    context_parts = [
        BASE_SYSTEM_PROMPT,
        assistant_line,
        profile_line,
        addressing_line,
        RESPONSE_INTENT_PROMPTS[intent],
    ]
    if summary:
        context_parts.append(f"Conversation summary:\n{summary}")
    if recent_messages:
        context_parts.append("Recent conversation:\n" + "\n".join(recent_messages))
    if semantic_memories:
        context_parts.append("Relevant long-term memories:\n" + "\n".join(semantic_memories))
    return "\n\n".join(context_parts)


def _build_file_qa_system_template(question_mode: str) -> str:
    if question_mode == "summary":
        return (
            "Template: summary.\n"
            "Open with a concise overall summary, then group key points by topic, and end with a short conclusion or judgment."
        )
    if question_mode == "compare":
        return (
            "Template: compare.\n"
            "Open with the overall conclusion, then compare by dimensions, and explicitly call out similarities, differences, and fit-for-use."
        )
    if question_mode == "extract":
        return (
            "Template: extract.\n"
            "Return a structured list of requested facts, fields, entities, or checklist items. Mark missing fields clearly."
        )
    if question_mode == "qa":
        return (
            "Template: direct QA.\n"
            "Answer the question first in one sentence, then cite the key supporting evidence in plain language."
        )
    return (
        "Template: overview.\n"
        "Provide a smooth introduction or overview first, then expand the most relevant supporting points."
    )


def _build_document_qa_instruction(question_mode: str) -> str:
    common = (
        "请基于上面的文件证据直接回答。不要只摘抄原文，要先理解再表达。"
        "正文结束后，单独输出一行 EVIDENCE_IDS: [你实际使用的片段编号]；如果没用到任何片段，就输出 EVIDENCE_IDS: []。"
    )
    if question_mode == "summary":
        return common + "这是总结类问题，请先给出整体概括，再整理关键要点，并补一句结论或判断。"
    if question_mode == "compare":
        return common + "这是对比类问题，请先给出总体结论，再按维度比较相同点、不同点和适用场景。"
    if question_mode == "extract":
        return common + "这是信息抽取类问题，请按清单或小标题输出，尽量结构化，缺失项明确标注。"
    if question_mode == "qa":
        return common + "这是具体问答，请先直接回答，再补充对应证据或依据。"
    return common + "这是文档介绍/综述类问题，请优先输出完整且通顺的说明，再补充关键点。"
