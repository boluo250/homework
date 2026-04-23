from app.core.models import Intent, UserProfile
from app.runtime.prompt_bundle_registry import (
    build_file_qa_prompt_bundle,
    build_intent_bundle,
    build_response_prompt_bundle,
    build_router_prompt_bundle,
)


def _user() -> UserProfile:
    return UserProfile(id="u1", client_id="c1", name="小李", email="xiaoli@example.com")


def test_intent_bundle_uses_task_registry_entry() -> None:
    bundle = build_intent_bundle(Intent.TASK_CRUD)
    assert bundle.bundle_id == "intent.task_crud"
    assert "## Task Bundle" in bundle.system_prompt


def test_response_prompt_bundle_uses_task_registry_entry() -> None:
    bundle = build_response_prompt_bundle(
        Intent.TASK_CRUD,
        _user(),
        assistant_name="TaskMate",
        summary="用户刚刚在整理待办。",
        recent_messages=["user: 帮我建个任务"],
    )
    assert bundle.bundle_id == "response.task_crud"
    assert "## Task Bundle" in bundle.system_prompt


def test_response_prompt_bundle_uses_research_registry_entry() -> None:
    bundle = build_response_prompt_bundle(
        Intent.DEEP_RESEARCH,
        _user(),
        assistant_name="TaskMate",
    )
    assert bundle.bundle_id == "response.deep_research"
    assert "## Research Bundle" in bundle.system_prompt


def test_router_prompt_bundle_uses_router_registry_entry() -> None:
    bundle = build_router_prompt_bundle(
        user=_user(),
        assistant_name="TaskMate",
        summary="刚聊过文档问答。",
        recent_messages=["user: 帮我看文件"],
        tasks=[],
        file_ids=["file_1"],
    )
    assert bundle.bundle_id == "router.main"
    assert "You are the action router for a Chinese task assistant." in bundle.system_prompt


def test_file_prompt_bundle_uses_registry_mode_template() -> None:
    bundle = build_file_qa_prompt_bundle(
        question="对比这两个方案",
        question_mode="compare",
        file_descriptions=["- a.md: 方案A", "- b.md: 方案B"],
        full_document_context="方案A...\n\n方案B...",
        evidence_blocks=["[片段 1] ...", "[片段 2] ..."],
    )
    assert bundle.bundle_id == "response.file_qa.compare"
    assert "Template: compare." in bundle.system_prompt
    assert "按维度比较相同点、不同点和适用场景" in (bundle.user_prompt or "")


def test_core_prompts_is_compatibility_shim_to_registry() -> None:
    bundle = build_response_prompt_bundle(
        Intent.GENERAL_CHAT,
        _user(),
        assistant_name="TaskMate",
        summary="刚聊过任务和文件。",
    )
    assert bundle.bundle_id == "response.general_chat"
    assert "You are a lightweight task and research assistant" in bundle.system_prompt
