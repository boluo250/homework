from __future__ import annotations

from app.core.models import TaskPriority, TaskStatus, ToolResult
from app.core.task_protocol import TaskToolAction
from app.state.task_state import TaskState
from app.tools.base import ToolOutcome


class TaskTool:
    def __init__(self, task_state: TaskState) -> None:
        self.task_state = task_state

    async def create(
        self,
        user_id: str,
        *,
        title: str,
        details: str = "",
        priority: TaskPriority | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        due_at: str | None = None,
    ):
        return await self.task_state.create_task(
            user_id,
            title=title,
            details=details,
            priority=priority,
            start_at=start_at,
            end_at=end_at,
            due_at=due_at,
        )

    async def list(self, user_id: str):
        return await self.task_state.list_tasks(user_id)

    async def get(self, user_id: str, *, task_id: str | None = None, title_hint: str | None = None):
        if task_id:
            return await self.task_state.get_task_by_id(user_id, task_id)
        if title_hint:
            return await self.task_state.find_task_by_title(user_id, title_hint)
        return None

    async def update(
        self,
        user_id: str,
        *,
        task_id: str | None = None,
        title_hint: str | None = None,
        title: str | None = None,
        details: str | None = None,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        due_at: str | None = None,
    ):
        return await self.task_state.update_task(
            user_id,
            task_id=task_id,
            title_hint=title_hint,
            title=title,
            details=details,
            status=status,
            priority=priority,
            start_at=start_at,
            end_at=end_at,
            due_at=due_at,
        )

    async def delete(self, user_id: str, *, task_id: str | None = None, title_hint: str | None = None) -> bool:
        return await self.task_state.delete_task(user_id, task_id=task_id, title_hint=title_hint)

    async def append_details(self, user_id: str, *, task_id: str, details: str):
        task = await self.task_state.get_task_by_id(user_id, task_id)
        if not task:
            return None
        merged = "\n".join(part for part in [task.details.strip(), details.strip()] if part)
        return await self.task_state.update_task(user_id, task_id=task_id, details=merged)

    async def execute(
        self,
        user_id: str,
        *,
        action: TaskToolAction,
        task_title: str | None,
        task_new_title: str | None,
        task_details: str | None,
        task_status: TaskStatus | None,
        task_priority: TaskPriority | None,
        task_start_at: str | None,
        task_end_at: str | None,
        task_due_at: str | None,
        target_ref: str | None,
    ) -> ToolOutcome:
        if action == TaskToolAction.CREATE:
            task = await self.create(
                user_id,
                title=task_title or "未命名任务",
                details=task_details or "",
                priority=task_priority,
                start_at=task_start_at,
                end_at=task_end_at,
                due_at=task_due_at,
            )
            details_suffix = f"，需求：{task.details}" if task.details else ""
            return ToolOutcome(
                reply=(
                    f"已创建你的待办：{task.title}，优先级 {task.priority.value}，状态 {task.status.value}"
                    f"{_task_schedule_suffix(task)}{details_suffix}。"
                ),
                tool_results=[ToolResult(name=TaskToolAction.CREATE.value, ok=True, content=task.to_dict())],
            )
        if action == TaskToolAction.UPDATE:
            task, error = await self.resolve_task_reference(user_id, title=task_title, target_ref=target_ref)
            if error:
                return ToolOutcome(
                    reply=error,
                    tool_results=[ToolResult(name=TaskToolAction.UPDATE.value, ok=False, content={"target_ref": target_ref})],
                )
            updated = await self.update(
                user_id,
                task_id=task.id if task else None,
                title_hint=task_title,
                title=task_new_title,
                details=task_details,
                status=task_status,
                priority=task_priority,
                start_at=task_start_at,
                end_at=task_end_at,
                due_at=task_due_at,
            )
            if not updated:
                return ToolOutcome(
                    reply="我没找到要更新的任务。你可以把任务名放进引号里再试一次。",
                    tool_results=[ToolResult(name=TaskToolAction.UPDATE.value, ok=False, content={"target_ref": target_ref})],
                )
            details_suffix = f"，需求：{updated.details}" if updated.details else ""
            return ToolOutcome(
                reply=(
                    f"任务已更新：{updated.title}，状态 {updated.status.value}，优先级 {updated.priority.value}"
                    f"{_task_schedule_suffix(updated)}{details_suffix}。"
                ),
                tool_results=[ToolResult(name=TaskToolAction.UPDATE.value, ok=True, content=updated.to_dict())],
            )
        if action == TaskToolAction.DELETE:
            task, error = await self.resolve_task_reference(user_id, title=task_title, target_ref=target_ref)
            if error:
                return ToolOutcome(
                    reply=error,
                    tool_results=[ToolResult(name=TaskToolAction.DELETE.value, ok=False, content={"target_ref": target_ref})],
                )
            deleted = await self.delete(user_id, task_id=task.id if task else None, title_hint=task_title)
            if not deleted:
                return ToolOutcome(
                    reply="我没有找到匹配的任务，暂时无法删除。",
                    tool_results=[ToolResult(name=TaskToolAction.DELETE.value, ok=False, content={"target_ref": target_ref})],
                )
            return ToolOutcome(
                reply=f"已删除你的待办：{task.title if task else task_title or '目标任务'}。",
                tool_results=[ToolResult(name=TaskToolAction.DELETE.value, ok=True, content=task.to_dict() if task else {})],
            )
        if action == TaskToolAction.GET:
            task, error = await self.resolve_task_reference(user_id, title=task_title, target_ref=target_ref)
            if error:
                return ToolOutcome(
                    reply=error,
                    tool_results=[ToolResult(name=TaskToolAction.GET.value, ok=False, content={"target_ref": target_ref})],
                )
            if not task:
                return ToolOutcome(
                    reply="我没找到这个任务。你可以把任务名放进引号里再试一次。",
                    tool_results=[ToolResult(name=TaskToolAction.GET.value, ok=False, content={"target_ref": target_ref})],
                )
            details = task.details or "暂无具体需求"
            reply = (
                f"待办详情：{task.title}\n"
                f"- 状态：{task.status.value}\n"
                f"- 优先级：{task.priority.value}\n"
                f"- 开始日期：{task.start_at or '未设置'}\n"
                f"- 结束日期：{task.end_at or task.due_at or '未设置'}\n"
                f"- 具体需求：{details}"
            )
            return ToolOutcome(
                reply=reply,
                tool_results=[ToolResult(name=TaskToolAction.GET.value, ok=True, content=task.to_dict())],
            )
        tasks = await self.list(user_id)
        if not tasks:
            return ToolOutcome(
                reply="你现在还没有自己创建的待办，我可以直接帮你记一个。",
                tool_results=[ToolResult(name=TaskToolAction.LIST.value, ok=True, content=[])],
            )
        lines = [
            f"- {task.title} | status={task.status.value} | priority={task.priority.value} | start={task.start_at or 'n/a'} | end={task.end_at or task.due_at or 'n/a'}"
            + (f" | details={task.details}" if task.details else "")
            for task in tasks
        ]
        return ToolOutcome(
            reply="你当前自己创建的待办如下：\n" + "\n".join(lines),
            tool_results=[ToolResult(name=TaskToolAction.LIST.value, ok=True, content=[task.to_dict() for task in tasks])],
        )

    async def resolve_task_reference(
        self,
        user_id: str,
        *,
        title: str | None,
        target_ref: str | None,
    ):
        tasks = await self.list(user_id)
        if title:
            task = await self.task_state.find_task_by_title(user_id, title)
            if task:
                return task, None
            return None, "我没找到这个任务。你可以把任务名放进引号里再试一次。"
        if not tasks:
            return None, "你现在还没有任务，我可以直接帮你创建一个。"
        if target_ref == "recent_task":
            return self._pick_recent_task(tasks), None
        if target_ref == "single_task" or len(tasks) == 1:
            return tasks[0], None
        return None, "我找到多个任务了。你可以直接告诉我任务名，或者说“删掉刚刚创建的那个任务”。"

    def _pick_recent_task(self, tasks: list):
        return max(
            enumerate(tasks),
            key=lambda item: (
                getattr(item[1], "updated_at", "") or "",
                getattr(item[1], "created_at", "") or "",
                item[0],
            ),
        )[1]


def _task_schedule_suffix(task) -> str:
    start = getattr(task, "start_at", None)
    end = getattr(task, "end_at", None) or getattr(task, "due_at", None)
    if start and end:
        return f"，开始 {start}，结束 {end}"
    if start:
        return f"，开始 {start}"
    if end:
        return f"，结束 {end}"
    return ""
