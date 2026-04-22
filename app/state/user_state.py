from __future__ import annotations

from app.core.models import UserProfile
from app.services.d1_repo import AppRepository


class UserState:
    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    async def get_by_client_id(self, client_id: str) -> UserProfile:
        return await self.repository.get_or_create_user(client_id)

    async def create_if_missing(self, client_id: str) -> UserProfile:
        return await self.repository.get_or_create_user(client_id)

    async def get_by_id(self, user_id: str) -> UserProfile | None:
        return await self.repository.get_user_by_id(user_id)

    async def update_profile(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
    ) -> UserProfile:
        return await self.repository.update_user_profile(user_id, name=name, email=email)

    async def clear_profile(self, user_id: str) -> UserProfile:
        return await self.repository.update_user_profile(user_id, name="", email="")
