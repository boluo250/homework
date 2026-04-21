from __future__ import annotations

from dataclasses import dataclass

from .models import ConversationMessage, ConversationSummary


@dataclass(slots=True)
class ContextBundle:
    summary_text: str | None
    recent_lines: list[str]
    should_refresh_summary: bool
    source_message_count: int


class ConversationContextManager:
    def __init__(self, recent_limit: int = 8, summary_trigger: int = 12) -> None:
        self.recent_limit = recent_limit
        self.summary_trigger = summary_trigger

    def build(
        self,
        messages: list[ConversationMessage],
        summary: ConversationSummary | None = None,
    ) -> ContextBundle:
        recent = messages[-self.recent_limit :]
        older = messages[: -self.recent_limit] if len(messages) > self.recent_limit else []
        summary_text = summary.summary if summary else None
        should_refresh = len(messages) >= self.summary_trigger and len(older) > 0
        if should_refresh:
            summary_text = self._merge_summary(summary_text, older)
        recent_lines = [f"{message.role.value}: {message.content}" for message in recent]
        return ContextBundle(
            summary_text=summary_text,
            recent_lines=recent_lines,
            should_refresh_summary=should_refresh,
            source_message_count=len(messages) - len(recent),
        )

    def _merge_summary(
        self,
        existing_summary: str | None,
        older_messages: list[ConversationMessage],
    ) -> str:
        compact_lines = []
        for message in older_messages[-6:]:
            compact_lines.append(f"- {message.role.value}: {message.content[:120]}")
        new_summary = "\n".join(compact_lines)
        if existing_summary:
            return f"{existing_summary}\n{new_summary}"
        return new_summary
