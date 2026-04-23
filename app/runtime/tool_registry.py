from __future__ import annotations

from app.core.task_protocol import TaskToolAction
from app.providers.llm_base import ToolCall, ToolDefinition


class ToolRegistry:
    def build_business_tools(self, *, file_ids: list[str]) -> list[ToolDefinition]:
        default_file_ids = file_ids[:6]
        return [
            ToolDefinition(
                name="save_profile",
                description="Persist the user's name and/or email when they explicitly provide it in the current message.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="recall_profile",
                description="Recall the stored user profile when the user asks what name/email/profile is remembered.",
                parameters={
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": ["name", "email", "profile"]},
                    },
                    "required": ["field"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="rename_assistant",
                description="Update the assistant nickname when the user assigns or changes it.",
                parameters={
                    "type": "object",
                    "properties": {"assistant_name": {"type": "string"}},
                    "required": ["assistant_name"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="get_assistant_name",
                description="Recall the assistant nickname when the user asks what you are called.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name=TaskToolAction.CREATE.value,
                description="Create a task with a concrete title and optional details, priority, and due date.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "details": {"type": "string"},
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        "due_at": {"type": "string"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name=TaskToolAction.UPDATE.value,
                description="Update an existing task by title or recent reference.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "target_ref": {"type": "string", "enum": ["recent_task", "single_task", "named_task"]},
                        "details": {"type": "string"},
                        "status": {"type": "string", "enum": ["todo", "in_progress", "done"]},
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        "due_at": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name=TaskToolAction.DELETE.value,
                description="Delete an existing task by title or recent reference.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "target_ref": {"type": "string", "enum": ["recent_task", "single_task", "named_task"]},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name=TaskToolAction.GET.value,
                description="Get details for an existing task by title or recent reference.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "target_ref": {"type": "string", "enum": ["recent_task", "single_task", "named_task"]},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name=TaskToolAction.LIST.value,
                description="List the user's tasks.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name="start_research",
                description="Start a deep research workflow for complex exploratory requests.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="search_web",
                description="Search the web for fresh information or direct lookups.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="list_uploaded_files",
                description=(
                    "List the user's uploaded documents from persistent storage (database metadata + vector counts). "
                    "Use when the user asks what files/documents exist, what is in the workspace or knowledge base, "
                    "or to enumerate uploads—not limited to the current UI selection."
                ),
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name="answer_file_question",
                description=(
                    "Answer a question using RAG over the user's indexed uploads. "
                    "When file_ids is omitted or empty, retrieval runs across all of the user's documents; "
                    "when the UI passes selected file_ids, prefer scoping to those files."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "file_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": default_file_ids,
                        },
                    },
                    "required": ["question"],
                    "additionalProperties": False,
                },
            ),
        ]

    def order_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolCall]:
        priority = {
            "save_profile": 0,
            "rename_assistant": 1,
            "recall_profile": 1,
            "get_assistant_name": 1,
            TaskToolAction.CREATE.value: 2,
            TaskToolAction.UPDATE.value: 2,
            TaskToolAction.DELETE.value: 2,
            TaskToolAction.GET.value: 2,
            TaskToolAction.LIST.value: 2,
            "start_research": 3,
            "search_web": 3,
            "list_uploaded_files": 2,
            "answer_file_question": 3,
        }
        ordered = sorted(enumerate(tool_calls), key=lambda item: (priority.get(item[1].name, 99), item[0]))
        return [item[1] for item in ordered]
