from __future__ import annotations

from .models import Intent, UserProfile


BASE_SYSTEM_PROMPT = """
You are a lightweight task and research assistant running inside Cloudflare Workers.
Always be concise, accurate, and action-oriented.
Prefer structured answers when tools returned structured data.
""".strip()


INTENT_PROMPTS: dict[Intent, str] = {
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


def build_system_prompt(
    intent: Intent,
    user: UserProfile,
    *,
    assistant_name: str,
    summary: str | None = None,
    recent_messages: list[str] | None = None,
    semantic_memories: list[str] | None = None,
) -> str:
    profile_line = (
        f"User profile: name={user.name or 'unknown'}, email={user.email or 'unknown'}."
    )
    assistant_line = f"Assistant nickname: {assistant_name}."
    addressing_line = (
        f"When replying in natural conversation, address the user as {user.name} when it feels natural."
        if user.name
        else "The user's preferred name is not known yet."
    )
    context_parts = [BASE_SYSTEM_PROMPT, assistant_line, profile_line, addressing_line, INTENT_PROMPTS[intent]]
    if summary:
        context_parts.append(f"Conversation summary:\n{summary}")
    if recent_messages:
        context_parts.append("Recent conversation:\n" + "\n".join(recent_messages))
    if semantic_memories:
        context_parts.append("Relevant long-term memories:\n" + "\n".join(semantic_memories))
    return "\n\n".join(context_parts)
