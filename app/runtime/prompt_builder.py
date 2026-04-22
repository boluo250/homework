from __future__ import annotations

from app.core.models import Intent, UserProfile
from app.core.prompts import build_system_prompt


def build_chat_system_prompt(
    intent: Intent,
    user: UserProfile,
    *,
    assistant_name: str,
    summary: str | None = None,
    recent_messages: list[str] | None = None,
    semantic_memories: list[str] | None = None,
    skill_instructions: str | None = None,
) -> str:
    prompt = build_system_prompt(
        intent,
        user,
        assistant_name=assistant_name,
        summary=summary,
        recent_messages=recent_messages,
        semantic_memories=semantic_memories,
    )
    if not skill_instructions:
        return prompt
    return prompt + "\n\nOperational skills:\n" + skill_instructions


def build_tool_router_prompt(
    *,
    user,
    assistant_name: str,
    summary: str | None,
    recent_messages: list[str],
    tasks: list,
    file_ids: list[str],
    skill_instructions: str | None = None,
) -> str:
    task_lines = [
        f"- {item.title} | status={item.status.value} | priority={item.priority.value}"
        for item in tasks[:8]
    ] or ["- 暂无任务"]
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
        "- If selected files are relevant, prefer answer_file_question.",
        "- For research requests like 调研 / 方案 / 对比 / tradeoff, prefer start_research.",
        f"Current assistant nickname: {assistant_name}",
        f"Current user profile: name={user.name or 'unknown'}, email={user.email or 'unknown'}",
        f"Selected file ids: {file_ids or []}",
        "Recent tasks:\n" + "\n".join(task_lines),
    ]
    if summary:
        context_parts.append(f"Conversation summary:\n{summary}")
    if recent_block:
        context_parts.append("Recent conversation:\n" + "\n".join(recent_block))
    if skill_instructions:
        context_parts.append("Operational skills:\n" + skill_instructions)
    return "\n\n".join(context_parts)
