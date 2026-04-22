from __future__ import annotations

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
    if not resolved_user_id:
        return HttpResponse.json({"error": "user_id or client_id is required"}, status=400)
    if request.method == "GET":
        tasks = await task_state.list_tasks(resolved_user_id)
        return HttpResponse.json({"tasks": [task.to_dict() for task in tasks], "user_id": resolved_user_id})
    return HttpResponse.json({"error": "Method not allowed"}, status=405)
