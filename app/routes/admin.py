from __future__ import annotations

from app.core.http import HttpRequest, HttpResponse
from app.state.file_state import FileState
from app.state.research_state import ResearchState
from app.state.task_state import TaskState
from app.state.user_state import UserState
from app.tools.workspace_admin_tool import WorkspaceAdminTool


async def handle_admin_reset(
    request: HttpRequest,
    repository,
    file_store,
    qdrant_store,
    *,
    workspace_admin_tool: WorkspaceAdminTool | None = None,
) -> HttpResponse:
    workspace_admin_tool = workspace_admin_tool or WorkspaceAdminTool(
        repository=repository,
        file_store=file_store,
        qdrant_store=qdrant_store,
        task_state=TaskState(repository),
        file_state=FileState(repository),
        research_state=ResearchState(repository),
        user_state=UserState(repository),
    )
    if request.method != "POST":
        return HttpResponse.json({"error": "Method not allowed"}, status=405)

    payload = request.json_data or {}
    if str(payload.get("confirm", "")).strip() != "RESET_ALL_DATA":
        return HttpResponse.json({"error": "confirm must equal RESET_ALL_DATA"}, status=400)
    return HttpResponse.json(await workspace_admin_tool.clear_all())
