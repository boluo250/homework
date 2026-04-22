from __future__ import annotations

from dataclasses import dataclass, field

from app.core.models import ToolResult


@dataclass(slots=True)
class ToolOutcome:
    reply: str
    tool_results: list[ToolResult] = field(default_factory=list)
