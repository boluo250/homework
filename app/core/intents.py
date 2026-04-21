from __future__ import annotations

from .models import Intent


TASK_KEYWORDS = {
    "任务",
    "待办",
    "todo",
    "task",
    "提醒",
    "安排",
    "创建任务",
    "新增任务",
    "删除任务",
    "完成任务",
}

SEARCH_KEYWORDS = {
    "搜索",
    "查一下",
    "联网",
    "最新",
    "今天",
    "实时",
    "news",
    "search",
}

RESEARCH_KEYWORDS = {
    "研究",
    "调研",
    "对比",
    "方案",
    "报告",
    "分析",
    "深度",
    "why",
    "tradeoff",
}

FILE_KEYWORDS = {
    "文件",
    "文档",
    "pdf",
    "docx",
    "markdown",
    "附件",
    "上传",
    "这份资料",
}

PROFILE_KEYWORDS = {
    "我叫",
    "我的名字",
    "邮箱",
    "email",
    "名字",
    "怎么称呼我",
    "叫你",
    "昵称",
}


def identify_intent(message: str, *, file_ids: list[str] | None = None) -> Intent:
    lowered = message.lower()
    if any(keyword in message for keyword in PROFILE_KEYWORDS) or "@" in lowered:
        return Intent.COLLECT_USER_PROFILE
    if file_ids or any(keyword in lowered or keyword in message for keyword in FILE_KEYWORDS):
        if "上传" not in message:
            return Intent.FILE_QA
    if any(keyword in lowered or keyword in message for keyword in RESEARCH_KEYWORDS):
        return Intent.DEEP_RESEARCH
    if any(keyword in lowered or keyword in message for keyword in SEARCH_KEYWORDS):
        return Intent.SEARCH_WEB
    if any(keyword in lowered or keyword in message for keyword in TASK_KEYWORDS):
        return Intent.TASK_CRUD
    return Intent.GENERAL_CHAT
