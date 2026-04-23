from __future__ import annotations

from app.core.models import Intent, UserProfile
from app.runtime.prompt_bundle_registry import (
    build_file_qa_prompt_bundle as build_file_qa_prompt_bundle_from_registry,
    build_response_prompt_bundle,
    build_router_prompt_bundle,
)


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
    bundle = build_response_prompt_bundle(
        intent,
        user,
        assistant_name=assistant_name,
        summary=summary,
        recent_messages=recent_messages,
        semantic_memories=semantic_memories,
        skill_instructions=skill_instructions,
    )
    return bundle.system_prompt


def build_file_qa_prompt_bundle(
    *,
    question: str,
    question_mode: str,
    file_descriptions: list[str],
    full_document_context: str,
    evidence_blocks: list[str],
) -> tuple[str, str]:
    bundle = build_file_qa_prompt_bundle_from_registry(
        question=question,
        question_mode=question_mode,
        file_descriptions=file_descriptions,
        full_document_context=full_document_context,
        evidence_blocks=evidence_blocks,
    )
    return bundle.system_prompt, bundle.user_prompt or ""


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
    bundle = build_router_prompt_bundle(
        user=user,
        assistant_name=assistant_name,
        summary=summary,
        recent_messages=recent_messages,
        tasks=tasks,
        file_ids=file_ids,
        skill_instructions=skill_instructions,
    )
    return bundle.system_prompt
