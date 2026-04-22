from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum

from .models import TaskPriority, TaskStatus


class TaskToolAction(str, Enum):
    CREATE = "create_task"
    UPDATE = "update_task"
    LIST = "list_tasks"
    DELETE = "delete_task"
    GET = "get_task"


@dataclass(slots=True)
class TaskToolCall:
    action: TaskToolAction
    task_id: str | None = None
    title: str | None = None
    details: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: str | None = None
    raw_query: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        payload = asdict(self)
        if self.status:
            payload["status"] = self.status.value
        if self.priority:
            payload["priority"] = self.priority.value
        payload["action"] = self.action.value
        return payload


_TASK_CREATE_PREFIXES = ("帮我创建", "帮我建", "创建", "新增", "添加", "记一个", "新建")
_TASK_DELETE_PREFIXES = ("删除", "移除", "取消")
_TASK_LIST_HINTS = ("列出", "看看", "显示", "有哪些", "所有", "清单", "列表")
_TASK_GET_HINTS = ("详情", "具体需求", "任务需求", "具体要求", "要求是什么", "说明")


def parse_task_tool_call(message: str) -> TaskToolCall:
    if any(token in message for token in _TASK_DELETE_PREFIXES):
        title = _extract_tail(message, _TASK_DELETE_PREFIXES)
        return TaskToolCall(action=TaskToolAction.DELETE, title=title or message)
    if any(token in message for token in _TASK_CREATE_PREFIXES):
        title = _extract_quoted_title(message) or _extract_tail(message, _TASK_CREATE_PREFIXES)
        return TaskToolCall(
            action=TaskToolAction.CREATE,
            title=_clean_title(title or message),
            details=_extract_details(message, title=title),
            priority=_extract_priority(message),
            due_at=_extract_due_at(message),
            raw_query=message,
        )
    if "完成" in message or "改成" in message or "更新" in message or "修改" in message:
        return TaskToolCall(
            action=TaskToolAction.UPDATE,
            title=_extract_quoted_title(message),
            details=_extract_details(message, title=_extract_quoted_title(message)),
            status=_extract_status(message),
            priority=_extract_priority(message),
            due_at=_extract_due_at(message),
            raw_query=message,
        )
    if any(token in message for token in _TASK_GET_HINTS) and ("任务" in message or "待办" in message):
        return TaskToolCall(
            action=TaskToolAction.GET,
            title=_extract_quoted_title(message) or _extract_title_hint_for_get(message),
            raw_query=message,
        )
    if any(token in message for token in _TASK_LIST_HINTS):
        return TaskToolCall(action=TaskToolAction.LIST, raw_query=message)
    return TaskToolCall(action=TaskToolAction.LIST, raw_query=message)


def _extract_quoted_title(message: str) -> str | None:
    matched = re.search(r"[“\"]([^”\"]+)[”\"]", message)
    if matched:
        return matched.group(1).strip()
    return None


def _extract_tail(message: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if prefix in message:
            tail = message.split(prefix, 1)[1].strip()
            return tail.strip("任务待办：: ")
    return None


def _clean_title(value: str) -> str:
    title = value
    for marker in ("，", ",", "。"):
        if marker in title:
            title = title.split(marker, 1)[0]
    for phrase in ("高优先级", "中优先级", "低优先级", "明天完成", "今天完成", "下周五前完成", "完成"):
        title = title.replace(phrase, "")
    title = title.replace("一个", "", 1).strip()
    if title.endswith("任务"):
        title = title[:-2]
    return title.strip(" ：:，。,.")


def _extract_priority(message: str) -> TaskPriority | None:
    if "高优先级" in message or "紧急" in message:
        return TaskPriority.HIGH
    if "低优先级" in message:
        return TaskPriority.LOW
    if "中优先级" in message or "普通优先级" in message:
        return TaskPriority.MEDIUM
    return None


def _extract_status(message: str) -> TaskStatus | None:
    if "完成" in message:
        return TaskStatus.DONE
    if "进行中" in message:
        return TaskStatus.IN_PROGRESS
    if "待办" in message or "未完成" in message:
        return TaskStatus.TODO
    return None


def _extract_due_at(message: str) -> str | None:
    patterns = [
        r"(今天|明天|后天|本周五|下周五|下周一)",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}月\d{1,2}日)",
    ]
    for pattern in patterns:
        matched = re.search(pattern, message)
        if matched:
            return matched.group(1)
    return None


def _extract_details(message: str, *, title: str | None) -> str | None:
    patterns = [
        r"(?:具体要求|任务要求|要求|需求|备注|说明)[:：，,\s]*(.+)$",
        r"(?:内容包括|包括|需要)[:：，,\s]*(.+)$",
    ]
    for pattern in patterns:
        matched = re.search(pattern, message)
        if matched:
            return _clean_details(matched.group(1))

    if title:
        remainder = message
        for quoted in (f'"{title}"', f"“{title}”"):
            remainder = remainder.replace(quoted, "", 1)
        for prefix in _TASK_CREATE_PREFIXES + _TASK_DELETE_PREFIXES:
            if prefix in remainder:
                remainder = remainder.split(prefix, 1)[1]
                break
        cleaned = _clean_details(remainder)
        if cleaned and cleaned != _clean_title(cleaned):
            return cleaned
    return None


def _clean_details(value: str) -> str | None:
    details = value.strip(" ，。:：")
    details = re.sub(r"(高优先级|中优先级|低优先级|普通优先级|紧急)", "", details)
    details = re.sub(r"(今天|明天|后天|本周五|下周五|下周一)(前)?完成", "", details)
    details = re.sub(r"\d{4}-\d{2}-\d{2}", "", details)
    details = re.sub(r"\d{1,2}月\d{1,2}日", "", details)
    details = details.replace("任务", "").strip(" ，。:：")
    return details or None


def _extract_title_hint_for_get(message: str) -> str | None:
    title = _extract_quoted_title(message)
    if title:
        return title

    normalized = message
    for prefix in ("帮我", "请", "麻烦", "查一下", "查查", "看看", "查看", "显示", "告诉我"):
        normalized = normalized.replace(prefix, "")
    for suffix in (
        "的详情",
        "详情",
        "的具体需求",
        "具体需求",
        "的具体要求",
        "具体要求",
        "的任务需求",
        "任务需求",
        "要求是什么",
        "说明",
    ):
        normalized = normalized.replace(suffix, "")
    normalized = normalized.replace("待办", "").strip(" ，。:：")
    if normalized.endswith("任务"):
        normalized = normalized[:-2]
    normalized = normalized.strip(" ，。:：")
    return normalized or None
