from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Intent(str, Enum):
    COLLECT_USER_PROFILE = "collect_user_profile"
    TASK_CRUD = "task_crud"
    SEARCH_WEB = "search_web"
    DEEP_RESEARCH = "deep_research"
    FILE_QA = "file_qa"
    GENERAL_CHAT = "general_chat"


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class UserProfile:
    id: str
    client_id: str
    name: str | None = None
    email: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def needs_profile_completion(self) -> bool:
        return not self.name or not self.email


@dataclass(slots=True)
class AssistantSettings:
    id: str
    user_id: str
    bot_name: str = "TaskMate"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class Conversation:
    id: str
    user_id: str
    title: str = "New Conversation"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ConversationMessage:
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    tool_calls_json: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ConversationSummary:
    id: str
    conversation_id: str
    summary: str
    source_message_count: int
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class PendingTaskDraftRecord:
    conversation_id: str
    title: str | None = None
    details: str | None = None
    priority: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class TaskRecord:
    id: str
    user_id: str
    title: str
    details: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    start_at: str | None = None
    end_at: str | None = None
    due_at: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["priority"] = self.priority.value
        return payload


@dataclass(slots=True)
class FileRecord:
    id: str
    user_id: str
    filename: str
    content_type: str
    size_bytes: int
    r2_key: str
    summary: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchJob:
    id: str
    user_id: str
    query: str
    status: str = "pending"
    report_markdown: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchJobState:
    job_id: str
    phase: str = "queued"
    current_step: int = 0
    total_steps: int = 0
    plan_json: str | None = None
    findings_json: str | None = None
    references_json: str | None = None
    last_error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchSubRun:
    id: str
    job_id: str
    title: str
    objective: str
    profile: str
    strategy_id: str
    status: str = "queued"
    step_index: int = 0
    search_queries_json: str | None = None
    summary: str | None = None
    artifacts_json: str | None = None
    last_error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["search_queries"] = _safe_json_loads(self.search_queries_json, default=[])
        payload["artifacts"] = _safe_json_loads(self.artifacts_json, default={})
        return payload


@dataclass(slots=True)
class ResearchEvent:
    id: str
    job_id: str
    event_type: str
    payload_json: str
    sub_run_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload"] = _safe_json_loads(self.payload_json, default={})
        return payload


@dataclass(slots=True)
class ToolResult:
    name: str
    ok: bool
    content: Any

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "content": self.content}


@dataclass(slots=True)
class ChatRequest:
    client_id: str
    message: str
    conversation_id: str | None = None
    file_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChatResponse:
    reply: str
    intent: Intent
    conversation_id: str
    tool_results: list[ToolResult] = field(default_factory=list)
    user_profile: UserProfile | None = None
    assistant_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "intent": self.intent.value,
            "conversation_id": self.conversation_id,
            "tool_results": [item.to_dict() for item in self.tool_results],
            "user_profile": asdict(self.user_profile) if self.user_profile else None,
            "assistant_name": self.assistant_name,
        }


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _safe_json_loads(value: str | None, *, default: Any) -> Any:
    if not value:
        return default
    try:
        return __import__("json").loads(value)
    except Exception:  # noqa: BLE001
        return default
