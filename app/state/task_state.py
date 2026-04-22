from __future__ import annotations

from app.core.models import TaskPriority, TaskRecord, TaskStatus
from app.services.d1_repo import AppRepository


class TaskState:
    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    async def create_task(
        self,
        user_id: str,
        *,
        title: str,
        details: str = "",
        priority: TaskPriority | None = None,
        due_at: str | None = None,
    ) -> TaskRecord:
        return await self.repository.create_task(
            user_id,
            title=title,
            details=details,
            priority=priority,
            due_at=due_at,
        )

    async def list_tasks(self, user_id: str) -> list[TaskRecord]:
        return await self.repository.list_tasks(user_id)

    async def get_task_by_id(self, user_id: str, task_id: str) -> TaskRecord | None:
        return await self.repository.get_task(user_id, task_id)

    async def find_task_by_title(self, user_id: str, title_hint: str) -> TaskRecord | None:
        return await self.repository.find_task_by_title(user_id, title_hint)

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
        return await self.repository.update_task(
            user_id,
            task_id=task_id,
            title_hint=title_hint,
            details=details,
            status=status,
            priority=priority,
            due_at=due_at,
        )

    async def delete_task(
        self,
        user_id: str,
        *,
        task_id: str | None = None,
        title_hint: str | None = None,
    ) -> bool:
        return await self.repository.delete_task(user_id, task_id=task_id, title_hint=title_hint)

    async def clear_tasks(self, user_id: str) -> int:
        tasks = await self.list_tasks(user_id)
        deleted = 0
        for task in tasks:
            if await self.delete_task(user_id, task_id=task.id):
                deleted += 1
        return deleted
