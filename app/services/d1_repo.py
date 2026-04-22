from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock

from app.core.models import (
    AssistantSettings,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    FileRecord,
    MessageRole,
    ResearchJob,
    ResearchJobState,
    TaskPriority,
    TaskRecord,
    TaskStatus,
    UserProfile,
    new_id,
    utc_now_iso,
)
from app.services.schema_sql import SCHEMA_SQL


class AppRepository(ABC):
    @abstractmethod
    async def get_or_create_user(self, client_id: str) -> UserProfile:
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> UserProfile | None:
        raise NotImplementedError

    @abstractmethod
    async def update_user_profile(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
    ) -> UserProfile:
        raise NotImplementedError

    @abstractmethod
    async def get_or_create_assistant_settings(self, user_id: str) -> AssistantSettings:
        raise NotImplementedError

    @abstractmethod
    async def update_assistant_name(self, user_id: str, bot_name: str) -> AssistantSettings:
        raise NotImplementedError

    @abstractmethod
    async def get_or_create_conversation(
        self,
        user_id: str,
        conversation_id: str | None = None,
    ) -> Conversation:
        raise NotImplementedError

    @abstractmethod
    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tool_calls_json: str | None = None,
    ) -> ConversationMessage:
        raise NotImplementedError

    @abstractmethod
    async def list_messages(self, conversation_id: str, limit: int = 30) -> list[ConversationMessage]:
        raise NotImplementedError

    @abstractmethod
    async def get_summary(self, conversation_id: str) -> ConversationSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def save_summary(
        self,
        conversation_id: str,
        summary: str,
        source_message_count: int,
    ) -> ConversationSummary:
        raise NotImplementedError

    @abstractmethod
    async def create_task(
        self,
        user_id: str,
        *,
        title: str,
        details: str = "",
        priority: TaskPriority | None = None,
        due_at: str | None = None,
    ) -> TaskRecord:
        raise NotImplementedError

    @abstractmethod
    async def list_tasks(self, user_id: str) -> list[TaskRecord]:
        raise NotImplementedError

    @abstractmethod
    async def find_task_by_title(self, user_id: str, title_hint: str) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def update_task(
        self,
        user_id: str,
        *,
        task_id: str | None = None,
        title_hint: str | None = None,
        details: str | None = None,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        due_at: str | None = None,
    ) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def delete_task(self, user_id: str, *, task_id: str | None = None, title_hint: str | None = None) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def get_task(self, user_id: str, task_id: str) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def create_file(
        self,
        user_id: str,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        r2_key: str,
        summary: str | None,
    ) -> FileRecord:
        raise NotImplementedError

    @abstractmethod
    async def list_files(self, user_id: str) -> list[FileRecord]:
        raise NotImplementedError

    @abstractmethod
    async def get_file(self, user_id: str, file_id: str) -> FileRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def update_file_name(self, user_id: str, file_id: str, filename: str) -> FileRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def delete_file(self, user_id: str, file_id: str) -> FileRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def create_research_job(self, user_id: str, query: str) -> ResearchJob:
        raise NotImplementedError

    @abstractmethod
    async def update_research_job(
        self,
        job_id: str,
        *,
        status: str,
        report_markdown: str | None = None,
    ) -> ResearchJob | None:
        raise NotImplementedError

    @abstractmethod
    async def get_research_job(self, job_id: str) -> ResearchJob | None:
        raise NotImplementedError

    @abstractmethod
    async def create_research_job_state(
        self,
        job_id: str,
        *,
        phase: str = "queued",
        current_step: int = 0,
        total_steps: int = 0,
        plan_json: str | None = None,
        findings_json: str | None = None,
        references_json: str | None = None,
        last_error: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> ResearchJobState:
        raise NotImplementedError

    @abstractmethod
    async def update_research_job_state(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        current_step: int | None = None,
        total_steps: int | None = None,
        plan_json: str | None = None,
        findings_json: str | None = None,
        references_json: str | None = None,
        last_error: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> ResearchJobState | None:
        raise NotImplementedError

    @abstractmethod
    async def get_research_job_state(self, job_id: str) -> ResearchJobState | None:
        raise NotImplementedError

    @abstractmethod
    async def reset_all_data(self) -> None:
        raise NotImplementedError


class InMemoryAppRepository(AppRepository):
    def __init__(self) -> None:
        self.users_by_client_id: dict[str, UserProfile] = {}
        self.assistant_settings_by_user_id: dict[str, AssistantSettings] = {}
        self.conversations_by_id: dict[str, Conversation] = {}
        self.messages_by_conversation_id: dict[str, list[ConversationMessage]] = {}
        self.summaries_by_conversation_id: dict[str, ConversationSummary] = {}
        self.tasks_by_user_id: dict[str, list[TaskRecord]] = {}
        self.files_by_user_id: dict[str, list[FileRecord]] = {}
        self.research_jobs_by_id: dict[str, ResearchJob] = {}
        self.research_job_states_by_id: dict[str, ResearchJobState] = {}

    async def get_or_create_user(self, client_id: str) -> UserProfile:
        user = self.users_by_client_id.get(client_id)
        if user:
            return user
        user = UserProfile(id=new_id("user"), client_id=client_id)
        self.users_by_client_id[client_id] = user
        return user

    async def get_user_by_id(self, user_id: str) -> UserProfile | None:
        return next((item for item in self.users_by_client_id.values() if item.id == user_id), None)

    async def update_user_profile(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
    ) -> UserProfile:
        user = next(item for item in self.users_by_client_id.values() if item.id == user_id)
        if name:
            user.name = name
        if email:
            user.email = email
        user.updated_at = utc_now_iso()
        return user

    async def get_or_create_assistant_settings(self, user_id: str) -> AssistantSettings:
        settings = self.assistant_settings_by_user_id.get(user_id)
        if settings:
            return settings
        settings = AssistantSettings(id=new_id("bot"), user_id=user_id)
        self.assistant_settings_by_user_id[user_id] = settings
        return settings

    async def update_assistant_name(self, user_id: str, bot_name: str) -> AssistantSettings:
        settings = await self.get_or_create_assistant_settings(user_id)
        settings.bot_name = bot_name
        settings.updated_at = utc_now_iso()
        return settings

    async def get_or_create_conversation(
        self,
        user_id: str,
        conversation_id: str | None = None,
    ) -> Conversation:
        if conversation_id and conversation_id in self.conversations_by_id:
            return self.conversations_by_id[conversation_id]
        conversation = Conversation(
            id=conversation_id or new_id("conv"),
            user_id=user_id,
            title="Chat Session",
        )
        self.conversations_by_id[conversation.id] = conversation
        self.messages_by_conversation_id.setdefault(conversation.id, [])
        return conversation

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tool_calls_json: str | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            id=new_id("msg"),
            conversation_id=conversation_id,
            role=MessageRole(role),
            content=content,
            tool_calls_json=tool_calls_json,
        )
        self.messages_by_conversation_id.setdefault(conversation_id, []).append(message)
        conversation = self.conversations_by_id[conversation_id]
        conversation.updated_at = utc_now_iso()
        return message

    async def list_messages(self, conversation_id: str, limit: int = 30) -> list[ConversationMessage]:
        return self.messages_by_conversation_id.get(conversation_id, [])[-limit:]

    async def get_summary(self, conversation_id: str) -> ConversationSummary | None:
        return self.summaries_by_conversation_id.get(conversation_id)

    async def save_summary(
        self,
        conversation_id: str,
        summary: str,
        source_message_count: int,
    ) -> ConversationSummary:
        existing = self.summaries_by_conversation_id.get(conversation_id)
        if existing:
            existing.summary = summary
            existing.source_message_count = source_message_count
            existing.updated_at = utc_now_iso()
            return existing
        new_summary = ConversationSummary(
            id=new_id("summary"),
            conversation_id=conversation_id,
            summary=summary,
            source_message_count=source_message_count,
        )
        self.summaries_by_conversation_id[conversation_id] = new_summary
        return new_summary

    async def create_task(
        self,
        user_id: str,
        *,
        title: str,
        details: str = "",
        priority: TaskPriority | None = None,
        due_at: str | None = None,
    ) -> TaskRecord:
        task = TaskRecord(
            id=new_id("task"),
            user_id=user_id,
            title=title,
            details=details,
            priority=priority or TaskPriority.MEDIUM,
            due_at=due_at,
        )
        self.tasks_by_user_id.setdefault(user_id, []).append(task)
        return task

    async def list_tasks(self, user_id: str) -> list[TaskRecord]:
        return list(self.tasks_by_user_id.get(user_id, []))

    async def find_task_by_title(self, user_id: str, title_hint: str) -> TaskRecord | None:
        normalized = title_hint.strip().lower()
        for task in reversed(self.tasks_by_user_id.get(user_id, [])):
            if normalized and normalized in task.title.lower():
                return task
        return None

    async def update_task(
        self,
        user_id: str,
        *,
        task_id: str | None = None,
        title_hint: str | None = None,
        details: str | None = None,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        due_at: str | None = None,
    ) -> TaskRecord | None:
        task = None
        if task_id:
            task = await self.get_task(user_id, task_id)
        elif title_hint:
            task = await self.find_task_by_title(user_id, title_hint)
        if not task:
            return None
        if details is not None:
            task.details = details
        if status:
            task.status = status
        if priority:
            task.priority = priority
        if due_at:
            task.due_at = due_at
        task.updated_at = utc_now_iso()
        return task

    async def delete_task(self, user_id: str, *, task_id: str | None = None, title_hint: str | None = None) -> bool:
        tasks = self.tasks_by_user_id.get(user_id, [])
        target = None
        if task_id:
            target = next((task for task in tasks if task.id == task_id), None)
        elif title_hint:
            target = await self.find_task_by_title(user_id, title_hint)
        if not target:
            return False
        tasks.remove(target)
        return True

    async def get_task(self, user_id: str, task_id: str) -> TaskRecord | None:
        return next((task for task in self.tasks_by_user_id.get(user_id, []) if task.id == task_id), None)

    async def create_file(
        self,
        user_id: str,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        r2_key: str,
        summary: str | None,
    ) -> FileRecord:
        record = FileRecord(
            id=new_id("file"),
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            r2_key=r2_key,
            summary=summary,
        )
        self.files_by_user_id.setdefault(user_id, []).append(record)
        return record

    async def list_files(self, user_id: str) -> list[FileRecord]:
        return list(self.files_by_user_id.get(user_id, []))

    async def get_file(self, user_id: str, file_id: str) -> FileRecord | None:
        return next((item for item in self.files_by_user_id.get(user_id, []) if item.id == file_id), None)

    async def update_file_name(self, user_id: str, file_id: str, filename: str) -> FileRecord | None:
        record = await self.get_file(user_id, file_id)
        if not record:
            return None
        record.filename = filename
        return record

    async def delete_file(self, user_id: str, file_id: str) -> FileRecord | None:
        files = self.files_by_user_id.get(user_id, [])
        target = next((item for item in files if item.id == file_id), None)
        if not target:
            return None
        files.remove(target)
        return target

    async def create_research_job(self, user_id: str, query: str) -> ResearchJob:
        job = ResearchJob(id=new_id("research"), user_id=user_id, query=query)
        self.research_jobs_by_id[job.id] = job
        return job

    async def update_research_job(
        self,
        job_id: str,
        *,
        status: str,
        report_markdown: str | None = None,
    ) -> ResearchJob | None:
        job = self.research_jobs_by_id.get(job_id)
        if not job:
            return None
        job.status = status
        if report_markdown is not None:
            job.report_markdown = report_markdown
        job.updated_at = utc_now_iso()
        return job

    async def get_research_job(self, job_id: str) -> ResearchJob | None:
        return self.research_jobs_by_id.get(job_id)

    async def create_research_job_state(
        self,
        job_id: str,
        *,
        phase: str = "queued",
        current_step: int = 0,
        total_steps: int = 0,
        plan_json: str | None = None,
        findings_json: str | None = None,
        references_json: str | None = None,
        last_error: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> ResearchJobState:
        state = ResearchJobState(
            job_id=job_id,
            phase=phase,
            current_step=current_step,
            total_steps=total_steps,
            plan_json=plan_json,
            findings_json=findings_json,
            references_json=references_json,
            last_error=last_error,
            started_at=started_at,
            completed_at=completed_at,
        )
        self.research_job_states_by_id[job_id] = state
        return state

    async def update_research_job_state(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        current_step: int | None = None,
        total_steps: int | None = None,
        plan_json: str | None = None,
        findings_json: str | None = None,
        references_json: str | None = None,
        last_error: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> ResearchJobState | None:
        state = self.research_job_states_by_id.get(job_id)
        if not state:
            return None
        if phase is not None:
            state.phase = phase
        if current_step is not None:
            state.current_step = current_step
        if total_steps is not None:
            state.total_steps = total_steps
        if plan_json is not None:
            state.plan_json = plan_json
        if findings_json is not None:
            state.findings_json = findings_json
        if references_json is not None:
            state.references_json = references_json
        if last_error is not None:
            state.last_error = last_error
        if started_at is not None:
            state.started_at = started_at
        if completed_at is not None:
            state.completed_at = completed_at
        state.updated_at = utc_now_iso()
        return state

    async def get_research_job_state(self, job_id: str) -> ResearchJobState | None:
        return self.research_job_states_by_id.get(job_id)

    async def reset_all_data(self) -> None:
        self.users_by_client_id.clear()
        self.assistant_settings_by_user_id.clear()
        self.conversations_by_id.clear()
        self.messages_by_conversation_id.clear()
        self.summaries_by_conversation_id.clear()
        self.tasks_by_user_id.clear()
        self.files_by_user_id.clear()
        self.research_jobs_by_id.clear()
        self.research_job_states_by_id.clear()


class SQLiteAppRepository(AppRepository):
    def __init__(self, db_path: Path, migrations_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = Lock()
        with self.lock:
            self.connection.execute("PRAGMA foreign_keys = ON;")
            self.connection.executescript(migrations_path.read_text(encoding="utf-8"))
            self.connection.executescript(SCHEMA_SQL)
            self.connection.commit()

    async def get_or_create_user(self, client_id: str) -> UserProfile:
        row = self._fetchone("SELECT * FROM users WHERE client_id = ?", (client_id,))
        if row:
            return _row_to_user(row)
        payload = UserProfile(id=new_id("user"), client_id=client_id)
        self._execute(
            """
            INSERT INTO users (id, client_id, name, email, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payload.id, payload.client_id, payload.name, payload.email, payload.created_at, payload.updated_at),
        )
        return payload

    async def get_user_by_id(self, user_id: str) -> UserProfile | None:
        row = self._fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return _row_to_user(row) if row else None

    async def update_user_profile(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
    ) -> UserProfile:
        current = await self.get_user_by_id(user_id)
        if not current:
            raise ValueError(f"User not found: {user_id}")
        next_name = name if name is not None else current.name
        next_email = email if email is not None else current.email
        updated_at = utc_now_iso()
        self._execute(
            "UPDATE users SET name = ?, email = ?, updated_at = ? WHERE id = ?",
            (next_name, next_email, updated_at, user_id),
        )
        return UserProfile(
            id=current.id,
            client_id=current.client_id,
            name=next_name,
            email=next_email,
            created_at=current.created_at,
            updated_at=updated_at,
        )

    async def get_or_create_assistant_settings(self, user_id: str) -> AssistantSettings:
        row = self._fetchone("SELECT * FROM assistant_settings WHERE user_id = ?", (user_id,))
        if row:
            return _row_to_assistant_settings(row)
        settings = AssistantSettings(id=new_id("bot"), user_id=user_id)
        self._execute(
            """
            INSERT INTO assistant_settings (id, user_id, bot_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (settings.id, settings.user_id, settings.bot_name, settings.created_at, settings.updated_at),
        )
        return settings

    async def update_assistant_name(self, user_id: str, bot_name: str) -> AssistantSettings:
        settings = await self.get_or_create_assistant_settings(user_id)
        updated_at = utc_now_iso()
        self._execute(
            "UPDATE assistant_settings SET bot_name = ?, updated_at = ? WHERE user_id = ?",
            (bot_name, updated_at, user_id),
        )
        return AssistantSettings(
            id=settings.id,
            user_id=user_id,
            bot_name=bot_name,
            created_at=settings.created_at,
            updated_at=updated_at,
        )

    async def get_or_create_conversation(
        self,
        user_id: str,
        conversation_id: str | None = None,
    ) -> Conversation:
        if conversation_id:
            row = self._fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
            if row:
                return _row_to_conversation(row)
        conversation = Conversation(
            id=conversation_id or new_id("conv"),
            user_id=user_id,
            title="Chat Session",
        )
        self._execute(
            """
            INSERT INTO conversations (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation.id, conversation.user_id, conversation.title, conversation.created_at, conversation.updated_at),
        )
        return conversation

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tool_calls_json: str | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            id=new_id("msg"),
            conversation_id=conversation_id,
            role=MessageRole(role),
            content=content,
            tool_calls_json=tool_calls_json,
        )
        self._execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, tool_calls_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.conversation_id,
                message.role.value,
                message.content,
                message.tool_calls_json,
                message.created_at,
            ),
        )
        self._execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now_iso(), conversation_id),
        )
        return message

    async def list_messages(self, conversation_id: str, limit: int = 30) -> list[ConversationMessage]:
        rows = self._fetchall(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        return [_row_to_message(row) for row in reversed(rows)]

    async def get_summary(self, conversation_id: str) -> ConversationSummary | None:
        row = self._fetchone("SELECT * FROM conversation_summaries WHERE conversation_id = ?", (conversation_id,))
        return _row_to_summary(row) if row else None

    async def save_summary(
        self,
        conversation_id: str,
        summary: str,
        source_message_count: int,
    ) -> ConversationSummary:
        existing = await self.get_summary(conversation_id)
        if existing:
            updated_at = utc_now_iso()
            self._execute(
                """
                UPDATE conversation_summaries
                SET summary = ?, source_message_count = ?, updated_at = ?
                WHERE conversation_id = ?
                """,
                (summary, source_message_count, updated_at, conversation_id),
            )
            return ConversationSummary(
                id=existing.id,
                conversation_id=conversation_id,
                summary=summary,
                source_message_count=source_message_count,
                created_at=existing.created_at,
                updated_at=updated_at,
            )
        payload = ConversationSummary(
            id=new_id("summary"),
            conversation_id=conversation_id,
            summary=summary,
            source_message_count=source_message_count,
        )
        self._execute(
            """
            INSERT INTO conversation_summaries
            (id, conversation_id, summary, source_message_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.id,
                payload.conversation_id,
                payload.summary,
                payload.source_message_count,
                payload.created_at,
                payload.updated_at,
            ),
        )
        return payload

    async def create_task(
        self,
        user_id: str,
        *,
        title: str,
        details: str = "",
        priority: TaskPriority | None = None,
        due_at: str | None = None,
    ) -> TaskRecord:
        payload = TaskRecord(
            id=new_id("task"),
            user_id=user_id,
            title=title,
            details=details,
            priority=priority or TaskPriority.MEDIUM,
            due_at=due_at,
        )
        self._execute(
            """
            INSERT INTO tasks
            (id, user_id, title, details, status, priority, due_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.id,
                payload.user_id,
                payload.title,
                payload.details,
                payload.status.value,
                payload.priority.value,
                payload.due_at,
                payload.created_at,
                payload.updated_at,
            ),
        )
        return payload

    async def list_tasks(self, user_id: str) -> list[TaskRecord]:
        rows = self._fetchall(
            "SELECT * FROM tasks WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC",
            (user_id,),
        )
        return [_row_to_task(row) for row in rows]

    async def find_task_by_title(self, user_id: str, title_hint: str) -> TaskRecord | None:
        normalized = title_hint.strip().lower()
        rows = await self.list_tasks(user_id)
        return next((task for task in rows if normalized and normalized in task.title.lower()), None)

    async def update_task(
        self,
        user_id: str,
        *,
        task_id: str | None = None,
        title_hint: str | None = None,
        details: str | None = None,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        due_at: str | None = None,
    ) -> TaskRecord | None:
        task = await self.get_task(user_id, task_id) if task_id else None
        if not task and title_hint:
            task = await self.find_task_by_title(user_id, title_hint)
        if not task:
            return None
        next_details = task.details if details is None else details
        next_status = status or task.status
        next_priority = priority or task.priority
        next_due_at = due_at if due_at is not None else task.due_at
        updated_at = utc_now_iso()
        self._execute(
            "UPDATE tasks SET details = ?, status = ?, priority = ?, due_at = ?, updated_at = ? WHERE id = ?",
            (next_details, next_status.value, next_priority.value, next_due_at, updated_at, task.id),
        )
        return TaskRecord(
            id=task.id,
            user_id=task.user_id,
            title=task.title,
            details=next_details,
            status=next_status,
            priority=next_priority,
            due_at=next_due_at,
            created_at=task.created_at,
            updated_at=updated_at,
        )

    async def delete_task(self, user_id: str, *, task_id: str | None = None, title_hint: str | None = None) -> bool:
        task = await self.get_task(user_id, task_id) if task_id else None
        if not task and title_hint:
            task = await self.find_task_by_title(user_id, title_hint)
        if not task:
            return False
        self._execute("DELETE FROM tasks WHERE id = ?", (task.id,))
        return True

    async def get_task(self, user_id: str, task_id: str | None) -> TaskRecord | None:
        if not task_id:
            return None
        row = self._fetchone("SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        return _row_to_task(row) if row else None

    async def create_file(
        self,
        user_id: str,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        r2_key: str,
        summary: str | None,
    ) -> FileRecord:
        payload = FileRecord(
            id=new_id("file"),
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            r2_key=r2_key,
            summary=summary,
        )
        self._execute(
            """
            INSERT INTO files (id, user_id, filename, content_type, size_bytes, r2_key, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.id,
                payload.user_id,
                payload.filename,
                payload.content_type,
                payload.size_bytes,
                payload.r2_key,
                payload.summary,
                payload.created_at,
            ),
        )
        return payload

    async def list_files(self, user_id: str) -> list[FileRecord]:
        rows = self._fetchall(
            "SELECT * FROM files WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return [_row_to_file(row) for row in rows]

    async def get_file(self, user_id: str, file_id: str) -> FileRecord | None:
        row = self._fetchone("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
        return _row_to_file(row) if row else None

    async def update_file_name(self, user_id: str, file_id: str, filename: str) -> FileRecord | None:
        record = await self.get_file(user_id, file_id)
        if not record:
            return None
        self._execute("UPDATE files SET filename = ? WHERE id = ?", (filename, file_id))
        return FileRecord(
            id=record.id,
            user_id=record.user_id,
            filename=filename,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            r2_key=record.r2_key,
            summary=record.summary,
            created_at=record.created_at,
        )

    async def delete_file(self, user_id: str, file_id: str) -> FileRecord | None:
        record = await self.get_file(user_id, file_id)
        if not record:
            return None
        self._execute("DELETE FROM files WHERE id = ?", (file_id,))
        return record

    async def create_research_job(self, user_id: str, query: str) -> ResearchJob:
        payload = ResearchJob(id=new_id("research"), user_id=user_id, query=query)
        self._execute(
            """
            INSERT INTO research_jobs (id, user_id, query, status, report_markdown, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.id,
                payload.user_id,
                payload.query,
                payload.status,
                payload.report_markdown,
                payload.created_at,
                payload.updated_at,
            ),
        )
        return payload

    async def update_research_job(
        self,
        job_id: str,
        *,
        status: str,
        report_markdown: str | None = None,
    ) -> ResearchJob | None:
        current = await self.get_research_job(job_id)
        if not current:
            return None
        updated_at = utc_now_iso()
        next_report = report_markdown if report_markdown is not None else current.report_markdown
        self._execute(
            "UPDATE research_jobs SET status = ?, report_markdown = ?, updated_at = ? WHERE id = ?",
            (status, next_report, updated_at, job_id),
        )
        return ResearchJob(
            id=current.id,
            user_id=current.user_id,
            query=current.query,
            status=status,
            report_markdown=next_report,
            created_at=current.created_at,
            updated_at=updated_at,
        )

    async def get_research_job(self, job_id: str) -> ResearchJob | None:
        row = self._fetchone("SELECT * FROM research_jobs WHERE id = ?", (job_id,))
        return _row_to_research_job(row) if row else None

    async def create_research_job_state(
        self,
        job_id: str,
        *,
        phase: str = "queued",
        current_step: int = 0,
        total_steps: int = 0,
        plan_json: str | None = None,
        findings_json: str | None = None,
        references_json: str | None = None,
        last_error: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> ResearchJobState:
        payload = ResearchJobState(
            job_id=job_id,
            phase=phase,
            current_step=current_step,
            total_steps=total_steps,
            plan_json=plan_json,
            findings_json=findings_json,
            references_json=references_json,
            last_error=last_error,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._execute(
            """
            INSERT INTO research_job_states
            (job_id, phase, current_step, total_steps, plan_json, findings_json, references_json, last_error, started_at, completed_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.job_id,
                payload.phase,
                payload.current_step,
                payload.total_steps,
                payload.plan_json,
                payload.findings_json,
                payload.references_json,
                payload.last_error,
                payload.started_at,
                payload.completed_at,
                payload.updated_at,
            ),
        )
        return payload

    async def update_research_job_state(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        current_step: int | None = None,
        total_steps: int | None = None,
        plan_json: str | None = None,
        findings_json: str | None = None,
        references_json: str | None = None,
        last_error: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> ResearchJobState | None:
        current = await self.get_research_job_state(job_id)
        if not current:
            return None
        next_payload = ResearchJobState(
            job_id=job_id,
            phase=current.phase if phase is None else phase,
            current_step=current.current_step if current_step is None else current_step,
            total_steps=current.total_steps if total_steps is None else total_steps,
            plan_json=current.plan_json if plan_json is None else plan_json,
            findings_json=current.findings_json if findings_json is None else findings_json,
            references_json=current.references_json if references_json is None else references_json,
            last_error=current.last_error if last_error is None else last_error,
            started_at=current.started_at if started_at is None else started_at,
            completed_at=current.completed_at if completed_at is None else completed_at,
        )
        updated_at = utc_now_iso()
        self._execute(
            """
            UPDATE research_job_states
            SET phase = ?, current_step = ?, total_steps = ?, plan_json = ?, findings_json = ?, references_json = ?, last_error = ?, started_at = ?, completed_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (
                next_payload.phase,
                next_payload.current_step,
                next_payload.total_steps,
                next_payload.plan_json,
                next_payload.findings_json,
                next_payload.references_json,
                next_payload.last_error,
                next_payload.started_at,
                next_payload.completed_at,
                updated_at,
                job_id,
            ),
        )
        next_payload.updated_at = updated_at
        return next_payload

    async def get_research_job_state(self, job_id: str) -> ResearchJobState | None:
        row = self._fetchone("SELECT * FROM research_job_states WHERE job_id = ?", (job_id,))
        return _row_to_research_job_state(row) if row else None

    async def reset_all_data(self) -> None:
        for table in (
            "messages",
            "conversation_summaries",
            "conversations",
            "assistant_settings",
            "tasks",
            "files",
            "research_jobs",
            "research_job_states",
            "users",
        ):
            self._execute(f"DELETE FROM {table}")

    def _fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.lock:
            cursor = self.connection.execute(sql, params)
            row = cursor.fetchone()
            cursor.close()
            return row

    def _fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            cursor = self.connection.execute(sql, params)
            rows = cursor.fetchall()
            cursor.close()
            return rows

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self.lock:
            self.connection.execute(sql, params)
            self.connection.commit()


def _row_to_user(row: sqlite3.Row) -> UserProfile:
    return UserProfile(
        id=row["id"],
        client_id=row["client_id"],
        name=row["name"],
        email=row["email"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_assistant_settings(row: sqlite3.Row) -> AssistantSettings:
    return AssistantSettings(
        id=row["id"],
        user_id=row["user_id"],
        bot_name=row["bot_name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: sqlite3.Row) -> ConversationMessage:
    return ConversationMessage(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=MessageRole(row["role"]),
        content=row["content"],
        tool_calls_json=row["tool_calls_json"],
        created_at=row["created_at"],
    )


def _row_to_summary(row: sqlite3.Row) -> ConversationSummary:
    return ConversationSummary(
        id=row["id"],
        conversation_id=row["conversation_id"],
        summary=row["summary"],
        source_message_count=row["source_message_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_task(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        details=row["details"],
        status=TaskStatus(row["status"]),
        priority=TaskPriority(row["priority"]),
        due_at=row["due_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_file(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        id=row["id"],
        user_id=row["user_id"],
        filename=row["filename"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        r2_key=row["r2_key"],
        summary=row["summary"],
        created_at=row["created_at"],
    )


def _row_to_research_job(row: sqlite3.Row) -> ResearchJob:
    return ResearchJob(
        id=row["id"],
        user_id=row["user_id"],
        query=row["query"],
        status=row["status"],
        report_markdown=row["report_markdown"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_research_job_state(row: sqlite3.Row) -> ResearchJobState:
    return ResearchJobState(
        job_id=row["job_id"],
        phase=row["phase"],
        current_step=int(row["current_step"]),
        total_steps=int(row["total_steps"]),
        plan_json=row["plan_json"],
        findings_json=row["findings_json"],
        references_json=row["references_json"],
        last_error=row["last_error"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        updated_at=row["updated_at"],
    )
