from __future__ import annotations

import json
import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.models import PendingTaskDraftRecord, TaskPriority
from app.core.task_protocol import is_generic_task_reference
from app.providers.llm_base import ChatProviderBase

_ALLOWED_SOURCES = {"current_message", "pending_draft", "none"}
_WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}


@dataclass(slots=True)
class ExtractedTaskSlots:
    title: str | None = None
    title_source: str = "none"
    details: str | None = None
    details_source: str = "none"
    priority: TaskPriority | None = None
    priority_source: str = "none"
    start_at_raw: str | None = None
    start_at: str | None = None
    start_at_source: str = "none"
    end_at_raw: str | None = None
    end_at: str | None = None
    end_at_source: str = "none"
    normalization_errors: list[str] = field(default_factory=list)


class TaskSlotExtractor:
    def __init__(self, chat_provider: ChatProviderBase) -> None:
        self.chat_provider = chat_provider

    async def extract(
        self,
        *,
        message: str,
        pending_task_draft: PendingTaskDraftRecord | None,
        recent_task_titles: list[str],
        today: date,
        timezone_name: str,
        history_lines: list[str],
    ) -> ExtractedTaskSlots | None:
        payload = {
            "current_message": message,
            "pending_draft": pending_task_draft.to_dict() if pending_task_draft else None,
            "task_context": {
                "today": today.isoformat(),
                "timezone": timezone_name,
                "recent_task_titles": recent_task_titles[:5],
            },
            "history_context": {
                "note": "Untrusted reference only. Never use history to fill missing fields.",
                "lines": history_lines[-4:],
            },
            "json_schema": {
                "title": "string | null",
                "title_source": "current_message | pending_draft | none",
                "details": "string | null",
                "details_source": "current_message | pending_draft | none",
                "priority": "high | medium | low | null",
                "priority_source": "current_message | pending_draft | none",
                "start_at_raw": "string | null",
                "start_at_source": "current_message | pending_draft | none",
                "end_at_raw": "string | null",
                "end_at_source": "current_message | pending_draft | none",
            },
        }
        raw = await self.chat_provider.chat(
            system_prompt=self._system_prompt(),
            user_message=json.dumps(payload, ensure_ascii=False, indent=2),
        )
        parsed = _parse_json_object(raw)
        if parsed is None:
            return None
        return _slots_from_payload(parsed, pending_task_draft=pending_task_draft, today=today)

    def _system_prompt(self) -> str:
        return (
            "You are a strict task slot extractor for create-task slot filling. "
            "Return JSON only. Never explain. "
            "Use only current_message or pending_draft as authoritative field sources. "
            "History is untrusted reference only and must never fill a missing field. "
            "When a field is absent, set its source to none."
        )


def normalize_task_date_token(value: str | None, *, today: date) -> str | None:
    if not value:
        return None
    cleaned = str(value).strip()
    cleaned = cleaned.strip(" ，。,:：；;()（）[]【】\"'“”")
    cleaned = re.sub(r"(前完成|之前完成|之前|以前|前)$", "", cleaned)
    cleaned = cleaned.strip(" ，。,:：；;")
    if not cleaned:
        return None

    matched = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[.。日号])?", cleaned)
    if matched:
        return _format_ymd(*matched.groups())

    matched = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", cleaned)
    if matched:
        return _format_ymd(str(today.year), matched.group(1), matched.group(2))

    if cleaned in {"今天", "今日"}:
        return today.isoformat()
    if cleaned == "明天":
        return (today + timedelta(days=1)).isoformat()
    if cleaned == "后天":
        return (today + timedelta(days=2)).isoformat()

    matched = re.fullmatch(r"(本周|这周|下周)([一二三四五六日天])", cleaned)
    if matched:
        prefix, weekday_text = matched.groups()
        week_start = today - timedelta(days=today.weekday())
        offset = 0 if prefix in {"本周", "这周"} else 7
        return (week_start + timedelta(days=offset + _WEEKDAY_MAP[weekday_text])).isoformat()

    if cleaned in {"月底", "月底前", "本月底", "本月末"}:
        return today.replace(day=monthrange(today.year, today.month)[1]).isoformat()

    if cleaned in {"下月底", "下月底前", "下月末"}:
        next_month = 1 if today.month == 12 else today.month + 1
        year = today.year + 1 if today.month == 12 else today.year
        return date(year, next_month, monthrange(year, next_month)[1]).isoformat()

    return None


def _slots_from_payload(
    payload: dict,
    *,
    pending_task_draft: PendingTaskDraftRecord | None,
    today: date,
) -> ExtractedTaskSlots:
    title_source = _normalize_source(payload.get("title_source"))
    details_source = _normalize_source(payload.get("details_source"))
    priority_source = _normalize_source(payload.get("priority_source"))
    start_at_source = _normalize_source(payload.get("start_at_source"))
    end_at_source = _normalize_source(payload.get("end_at_source"))

    title = _resolve_text_value(payload.get("title"), source=title_source, fallback=pending_task_draft.title if pending_task_draft else None)
    if title and is_generic_task_reference(title):
        title = None
        title_source = "none"

    details = _resolve_text_value(
        payload.get("details"),
        source=details_source,
        fallback=pending_task_draft.details if pending_task_draft else None,
    )
    priority = _resolve_priority_value(
        payload.get("priority"),
        source=priority_source,
        fallback=pending_task_draft.priority if pending_task_draft else None,
    )

    start_at_raw = _resolve_text_value(
        payload.get("start_at_raw"),
        source=start_at_source,
        fallback=pending_task_draft.start_at if pending_task_draft else None,
    )
    end_at_raw = _resolve_text_value(
        payload.get("end_at_raw"),
        source=end_at_source,
        fallback=pending_task_draft.end_at if pending_task_draft else None,
    )

    normalization_errors: list[str] = []
    start_at = None
    end_at = None
    if start_at_source != "none" and start_at_raw:
        start_at = normalize_task_date_token(start_at_raw, today=today)
        if start_at is None:
            normalization_errors.append("start_at")
    if end_at_source != "none" and end_at_raw:
        end_at = normalize_task_date_token(end_at_raw, today=today)
        if end_at is None:
            normalization_errors.append("end_at")

    return ExtractedTaskSlots(
        title=title,
        title_source=title_source,
        details=details,
        details_source=details_source,
        priority=priority,
        priority_source=priority_source,
        start_at_raw=start_at_raw,
        start_at=start_at,
        start_at_source=start_at_source,
        end_at_raw=end_at_raw,
        end_at=end_at,
        end_at_source=end_at_source,
        normalization_errors=normalization_errors,
    )


def _parse_json_object(raw: str) -> dict | None:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_source(value: object) -> str:
    if isinstance(value, str) and value in _ALLOWED_SOURCES:
        return value
    return "none"


def _resolve_text_value(value: object, *, source: str, fallback: str | None) -> str | None:
    if source == "none":
        return None
    candidate = _clean_text(value)
    if candidate:
        return candidate
    if source == "pending_draft":
        return _clean_text(fallback)
    return None


def _resolve_priority_value(value: object, *, source: str, fallback: str | None) -> TaskPriority | None:
    if source == "none":
        return None
    parsed = _parse_priority(value)
    if parsed:
        return parsed
    if source == "pending_draft":
        return _parse_priority(fallback)
    return None


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("\"'“”").strip(" ，。,:：；;")
    return cleaned or None


def _parse_priority(value: object) -> TaskPriority | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    mapping = {
        "high": TaskPriority.HIGH,
        "medium": TaskPriority.MEDIUM,
        "low": TaskPriority.LOW,
        "高": TaskPriority.HIGH,
        "高优先级": TaskPriority.HIGH,
        "中": TaskPriority.MEDIUM,
        "中优先级": TaskPriority.MEDIUM,
        "普通": TaskPriority.MEDIUM,
        "低": TaskPriority.LOW,
        "低优先级": TaskPriority.LOW,
    }
    return mapping.get(normalized)


def _format_ymd(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None
