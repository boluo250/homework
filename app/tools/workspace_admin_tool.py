from __future__ import annotations

from app.services.d1_repo import AppRepository
from app.state.file_state import FileState
from app.state.research_state import ResearchState
from app.state.task_state import TaskState
from app.state.user_state import UserState


class WorkspaceAdminTool:
    def __init__(
        self,
        *,
        repository: AppRepository,
        file_store,
        qdrant_store,
        task_state: TaskState,
        file_state: FileState,
        research_state: ResearchState,
        user_state: UserState,
    ) -> None:
        self.repository = repository
        self.file_store = file_store
        self.qdrant_store = qdrant_store
        self.task_state = task_state
        self.file_state = file_state
        self.research_state = research_state
        self.user_state = user_state

    async def clear_tasks(self, user_id: str) -> int:
        return await self.task_state.clear_tasks(user_id)

    async def clear_files(self, user_id: str) -> int:
        files = await self.file_state.list_files(user_id)
        deleted = 0
        for item in files:
            await self.qdrant_store.delete_by_file(user_id=user_id, file_id=item.id)
            await self.file_store.delete_file(item.r2_key)
            removed = await self.file_state.delete_file(user_id, item.id)
            if removed is not None:
                deleted += 1
        return deleted

    async def clear_research(self, user_id: str) -> int:
        return await self.research_state.clear_jobs(user_id)

    async def clear_profile(self, user_id: str):
        return await self.user_state.clear_profile(user_id)

    async def clear_all(self) -> dict:
        await self.repository.reset_all_data()
        deleted_r2_count = 0
        if hasattr(self.file_store, "delete_all_files"):
            result = await self.file_store.delete_all_files()
            deleted_r2_count = int(result or 0)
        await self.qdrant_store.reset_collection()
        return {
            "ok": True,
            "deleted_r2_count": deleted_r2_count,
            "message": "All D1, R2, and Qdrant data has been cleared.",
        }
