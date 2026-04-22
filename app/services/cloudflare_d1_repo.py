from __future__ import annotations

from typing import Any

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
from app.services.d1_repo import AppRepository
from app.services.schema_sql import SCHEMA_SQL


class CloudflareD1Repository(AppRepository):
    def __init__(self, db_binding: Any, migrations_sql: str = SCHEMA_SQL) -> None:
        self.db = db_binding
        self.migrations_sql = migrations_sql
        self._schema_ready = False

    async def get_or_create_user(self, client_id: str) -> UserProfile:
        await self._ensure_schema()
        row = await self._first("SELECT * FROM users WHERE client_id = ?", (client_id,))
        if row:
            return _row_to_user(row)
        payload = UserProfile(id=new_id("user"), client_id=client_id)
        await self._run(
            """
            INSERT INTO users (id, client_id, name, email, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payload.id, payload.client_id, payload.name, payload.email, payload.created_at, payload.updated_at),
        )
        return payload

    async def get_user_by_id(self, user_id: str) -> UserProfile | None:
        await self._ensure_schema()
        row = await self._first("SELECT * FROM users WHERE id = ?", (user_id,))
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
        updated_at = utc_now_iso()
        next_name = current.name if name is None else name
        next_email = current.email if email is None else email
        await self._run(
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
        await self._ensure_schema()
        row = await self._first("SELECT * FROM assistant_settings WHERE user_id = ?", (user_id,))
        if row:
            return _row_to_assistant_settings(row)
        payload = AssistantSettings(id=new_id("bot"), user_id=user_id)
        await self._run(
            """
            INSERT INTO assistant_settings (id, user_id, bot_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.id, payload.user_id, payload.bot_name, payload.created_at, payload.updated_at),
        )
        return payload

    async def update_assistant_name(self, user_id: str, bot_name: str) -> AssistantSettings:
        settings = await self.get_or_create_assistant_settings(user_id)
        updated_at = utc_now_iso()
        await self._run(
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
        await self._ensure_schema()
        if conversation_id:
            row = await self._first("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
            if row:
                return _row_to_conversation(row)
        payload = Conversation(id=conversation_id or new_id("conv"), user_id=user_id, title="Chat Session")
        await self._run(
            """
            INSERT INTO conversations (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.id, payload.user_id, payload.title, payload.created_at, payload.updated_at),
        )
        return payload

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tool_calls_json: str | None = None,
    ) -> ConversationMessage:
        await self._ensure_schema()
        payload = ConversationMessage(
            id=new_id("msg"),
            conversation_id=conversation_id,
            role=MessageRole(role),
            content=content,
            tool_calls_json=tool_calls_json,
        )
        await self._run(
            """
            INSERT INTO messages (id, conversation_id, role, content, tool_calls_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.id,
                payload.conversation_id,
                payload.role.value,
                payload.content,
                payload.tool_calls_json,
                payload.created_at,
            ),
        )
        await self._run(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now_iso(), conversation_id),
        )
        return payload

    async def list_messages(self, conversation_id: str, limit: int = 30) -> list[ConversationMessage]:
        await self._ensure_schema()
        rows = await self._all(
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
        await self._ensure_schema()
        row = await self._first("SELECT * FROM conversation_summaries WHERE conversation_id = ?", (conversation_id,))
        return _row_to_summary(row) if row else None

    async def save_summary(
        self,
        conversation_id: str,
        summary: str,
        source_message_count: int,
    ) -> ConversationSummary:
        await self._ensure_schema()
        existing = await self.get_summary(conversation_id)
        if existing:
            updated_at = utc_now_iso()
            await self._run(
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
        await self._run(
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
        await self._ensure_schema()
        payload = TaskRecord(
            id=new_id("task"),
            user_id=user_id,
            title=title,
            details=details,
            priority=priority or TaskPriority.MEDIUM,
            due_at=due_at,
        )
        await self._run(
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
        await self._ensure_schema()
        rows = await self._all(
            "SELECT * FROM tasks WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC",
            (user_id,),
        )
        return [_row_to_task(row) for row in rows]

    async def find_task_by_title(self, user_id: str, title_hint: str) -> TaskRecord | None:
        normalized = title_hint.strip().lower()
        for task in await self.list_tasks(user_id):
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
        task = await self.get_task(user_id, task_id) if task_id else None
        if not task and title_hint:
            task = await self.find_task_by_title(user_id, title_hint)
        if not task:
            return None
        updated_at = utc_now_iso()
        next_details = task.details if details is None else details
        next_status = status or task.status
        next_priority = priority or task.priority
        next_due_at = task.due_at if due_at is None else due_at
        await self._run(
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
        await self._run("DELETE FROM tasks WHERE id = ?", (task.id,))
        return True

    async def get_task(self, user_id: str, task_id: str) -> TaskRecord | None:
        await self._ensure_schema()
        row = await self._first("SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
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
        await self._ensure_schema()
        payload = FileRecord(
            id=new_id("file"),
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            r2_key=r2_key,
            summary=summary,
        )
        await self._run(
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
        await self._ensure_schema()
        rows = await self._all("SELECT * FROM files WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return [_row_to_file(row) for row in rows]

    async def get_file(self, user_id: str, file_id: str) -> FileRecord | None:
        await self._ensure_schema()
        row = await self._first("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
        return _row_to_file(row) if row else None

    async def update_file_name(self, user_id: str, file_id: str, filename: str) -> FileRecord | None:
        record = await self.get_file(user_id, file_id)
        if not record:
            return None
        await self._run("UPDATE files SET filename = ? WHERE id = ?", (filename, file_id))
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
        await self._run("DELETE FROM files WHERE id = ?", (file_id,))
        return record

    async def create_research_job(self, user_id: str, query: str) -> ResearchJob:
        await self._ensure_schema()
        payload = ResearchJob(id=new_id("research"), user_id=user_id, query=query)
        await self._run(
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
        next_report = current.report_markdown if report_markdown is None else report_markdown
        await self._run(
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
        await self._ensure_schema()
        row = await self._first("SELECT * FROM research_jobs WHERE id = ?", (job_id,))
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
        await self._ensure_schema()
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
        await self._run(
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
        await self._run(
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
        await self._ensure_schema()
        row = await self._first("SELECT * FROM research_job_states WHERE job_id = ?", (job_id,))
        return _row_to_research_job_state(row) if row else None

    async def reset_all_data(self) -> None:
        await self._ensure_schema()
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
            await self._run(f"DELETE FROM {table}")

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        for statement in _split_migration_statements(self.migrations_sql):
            await self._run(statement)
        self._schema_ready = True

    async def _run(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        statement = self.db.prepare(sql)
        if params:
            statement = statement.bind(*_coerce_params(params))
        return await statement.run()

    async def _first(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if params:
            statement = statement.bind(*_coerce_params(params))
        row = await statement.first()
        return _to_python(row)

    async def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if params:
            statement = statement.bind(*_coerce_params(params))
        response = await statement.all()
        parsed = _to_python(response) or {}
        results = parsed.get("results", []) if isinstance(parsed, dict) else []
        return results


def _coerce_params(params: tuple[Any, ...]) -> tuple[Any, ...]:
    # D1's bind() rejects Python None (becomes JS undefined); use JS null instead
    try:
        import js  # pyodide runtime
        js_null = js.JSON.parse("null")
        return tuple(js_null if v is None else v for v in params)
    except ImportError:
        return params


def _to_python(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_py"):
        return value.to_py()
    return value


def _split_migration_statements(sql: str) -> list[str]:
    statements: list[str] = []
    for chunk in sql.split(";"):
        statement = chunk.strip()
        if not statement:
            continue
        if statement.upper().startswith("PRAGMA "):
            continue
        statements.append(statement)
    return statements


def _row_to_user(row: dict[str, Any]) -> UserProfile:
    return UserProfile(
        id=row["id"],
        client_id=row["client_id"],
        name=row.get("name"),
        email=row.get("email"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_assistant_settings(row: dict[str, Any]) -> AssistantSettings:
    return AssistantSettings(
        id=row["id"],
        user_id=row["user_id"],
        bot_name=row["bot_name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_conversation(row: dict[str, Any]) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: dict[str, Any]) -> ConversationMessage:
    return ConversationMessage(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=MessageRole(row["role"]),
        content=row["content"],
        tool_calls_json=row.get("tool_calls_json"),
        created_at=row["created_at"],
    )


def _row_to_summary(row: dict[str, Any]) -> ConversationSummary:
    return ConversationSummary(
        id=row["id"],
        conversation_id=row["conversation_id"],
        summary=row["summary"],
        source_message_count=int(row["source_message_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_task(row: dict[str, Any]) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        details=row["details"],
        status=TaskStatus(row["status"]),
        priority=TaskPriority(row["priority"]),
        due_at=row.get("due_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_file(row: dict[str, Any]) -> FileRecord:
    return FileRecord(
        id=row["id"],
        user_id=row["user_id"],
        filename=row["filename"],
        content_type=row["content_type"],
        size_bytes=int(row["size_bytes"]),
        r2_key=row["r2_key"],
        summary=row.get("summary"),
        created_at=row["created_at"],
    )


def _row_to_research_job(row: dict[str, Any]) -> ResearchJob:
    return ResearchJob(
        id=row["id"],
        user_id=row["user_id"],
        query=row["query"],
        status=row["status"],
        report_markdown=row.get("report_markdown"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_research_job_state(row: dict[str, Any]) -> ResearchJobState:
    return ResearchJobState(
        job_id=row["job_id"],
        phase=row["phase"],
        current_step=int(row["current_step"]),
        total_steps=int(row["total_steps"]),
        plan_json=row.get("plan_json"),
        findings_json=row.get("findings_json"),
        references_json=row.get("references_json"),
        last_error=row.get("last_error"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        updated_at=row["updated_at"],
    )
