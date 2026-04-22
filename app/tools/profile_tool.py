from __future__ import annotations

from app.core.models import UserProfile
from app.state.user_state import UserState


class ProfileTool:
    def __init__(self, user_state: UserState) -> None:
        self.user_state = user_state

    async def get(self, user: UserProfile, field: str = "profile") -> str:
        if field == "email":
            if user.email:
                return f"我记得你的邮箱是 {user.email}。"
            return "我现在还不知道你的邮箱，你可以直接告诉我。"
        if field == "profile":
            known_bits = []
            if user.name:
                known_bits.append(f"名字是 {user.name}")
            if user.email:
                known_bits.append(f"邮箱是 {user.email}")
            if known_bits:
                return "我现在记得你的资料：" + "，".join(known_bits) + "。"
            return "我现在还没有记住你的资料。你可以先告诉我名字和邮箱。"
        if user.name:
            return f"我记得你叫 {user.name}。"
        return "我现在还不知道你的名字，你可以直接告诉我。"

    async def set(
        self,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
    ) -> UserProfile:
        return await self.user_state.update_profile(user_id, name=name, email=email)

    def is_complete(self, user: UserProfile) -> bool:
        return not user.needs_profile_completion

    async def clear(self, user_id: str) -> UserProfile:
        return await self.user_state.clear_profile(user_id)

    def build_completion_reply(self, user: UserProfile, assistant_name: str) -> str:
        missing = []
        if not user.name:
            missing.append("名字")
        if not user.email:
            missing.append("邮箱")
        if user.name and not user.email:
            return f"我已经记住你叫 {user.name} 了。接下来还需要你的邮箱，这样 {assistant_name} 后面才能稳定记住并称呼你。"
        if user.email and not user.name:
            return f"我已经记住你的邮箱 {user.email}。接下来告诉我你的名字，这样 {assistant_name} 后面就能直接称呼你。"
        return f"开始之前，先告诉我你的{'和'.join(missing)}，我会先记下来。"

    def build_saved_reply(self, user: UserProfile, assistant_name: str, *, bot_name_updated: bool) -> str:
        parts = [f"好的，我记住了。你是 {user.name}，邮箱是 {user.email}。"]
        if bot_name_updated:
            parts.append(f"以后你可以叫我 {assistant_name}。")
        else:
            parts.append(f"后面我会直接称呼你为 {user.name}。")
        return " ".join(parts)
