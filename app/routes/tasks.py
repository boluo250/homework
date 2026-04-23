from __future__ import annotations

from app.core.models import TaskPriority, TaskStatus
from app.core.http import HttpRequest, HttpResponse
from app.state.task_state import TaskState


async def handle_tasks(
    request: HttpRequest,
    repository,
    *,
    user_id: str | None = None,
    task_state: TaskState | None = None,
) -> HttpResponse:
    task_state = task_state or TaskState(repository)
    resolved_user_id = user_id or request.query.get("user_id")
    client_id = request.query.get("client_id")
    if not resolved_user_id and client_id:
        user = await repository.get_or_create_user(client_id)
        resolved_user_id = user.id
    if request.method == "GET":
        if not resolved_user_id:
            return HttpResponse.json({"error": "user_id or client_id is required"}, status=400)
        tasks = await task_state.list_tasks(resolved_user_id)
        return HttpResponse.json({"tasks": [task.to_dict() for task in tasks], "user_id": resolved_user_id})
    if request.method == "PATCH":
        payload = request.json_data or {}
        client_id = str(payload.get("client_id", "")).strip() or client_id
        if not resolved_user_id and client_id:
            user = await repository.get_or_create_user(client_id)
            resolved_user_id = user.id
        if not resolved_user_id:
            return HttpResponse.json({"error": "user_id or client_id is required"}, status=400)

        task_id = str(payload.get("task_id", "")).strip()
        if not task_id:
            return HttpResponse.json({"error": "task_id is required"}, status=400)

        title = None
        if "title" in payload:
            title = str(payload.get("title", "")).strip()
            if not title:
                return HttpResponse.json({"error": "title cannot be empty"}, status=400)

        details = None
        if "details" in payload:
            details = str(payload.get("details", "")).strip()

        status = _parse_task_status(payload.get("status"))
        if "status" in payload and status is None:
            return HttpResponse.json({"error": "status must be one of todo, in_progress, done"}, status=400)

        priority = _parse_task_priority(payload.get("priority"))
        if "priority" in payload and priority is None:
            return HttpResponse.json({"error": "priority must be one of high, medium, low"}, status=400)

        start_at = _optional_date_text(payload, "start_at")
        end_at = _optional_date_text(payload, "end_at")
        due_at = end_at if "end_at" in payload else None
        updated = await task_state.update_task(
            resolved_user_id,
            task_id=task_id,
            title=title,
            details=details,
            status=status,
            priority=priority,
            start_at=start_at,
            end_at=end_at,
            due_at=due_at,
        )
        if not updated:
            return HttpResponse.json({"error": "task not found"}, status=404)
        return HttpResponse.json({"task": updated.to_dict(), "user_id": resolved_user_id})
    return HttpResponse.json({"error": "Method not allowed"}, status=405)


def _parse_task_status(value: object) -> TaskStatus | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    try:
        return TaskStatus(value)
    except ValueError:
        return None


def _parse_task_priority(value: object) -> TaskPriority | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    try:
        return TaskPriority(value)
    except ValueError:
        return None


def _optional_date_text(payload: dict, key: str) -> str | None:
    if key not in payload:
        return None
    value = str(payload.get(key, "")).strip()
    return value or None
