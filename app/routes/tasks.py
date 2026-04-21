from __future__ import annotations

from app.core.http import HttpRequest, HttpResponse


async def handle_tasks(request: HttpRequest, repository, *, user_id: str | None = None) -> HttpResponse:
    resolved_user_id = user_id or request.query.get("user_id")
    client_id = request.query.get("client_id")
    if not resolved_user_id and client_id:
        user = await repository.get_or_create_user(client_id)
        resolved_user_id = user.id
    if not resolved_user_id:
        return HttpResponse.json({"error": "user_id or client_id is required"}, status=400)
    if request.method == "GET":
        tasks = await repository.list_tasks(resolved_user_id)
        return HttpResponse.json({"tasks": [task.to_dict() for task in tasks], "user_id": resolved_user_id})
    return HttpResponse.json({"error": "Method not allowed"}, status=405)
