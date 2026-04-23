from __future__ import annotations

from .models import Intent


TASK_KEYWORDS = {
    "我的任务",
    "我的待办",
    "待办",
    "todo",
    "task",
    "提醒我",
    "给我记",
    "帮我记",
    "创建任务",
    "新增任务",
    "删除任务",
    "完成任务",
}

PROJECT_TASK_EXCLUSIONS = {
    "项目任务",
    "项目本身的任务",
    "开发任务",
    "实现任务",
    "系统任务",
    "模块任务",
    "任务拆解",
    "任务模块",
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
    "我的姓名",
    "姓名",
    "邮箱",
    "email",
    "叫我",
    "你可以叫我",
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
    if looks_like_user_task_request(message):
        return Intent.TASK_CRUD
    return Intent.GENERAL_CHAT


def looks_like_user_task_request(message: str) -> bool:
    lowered = message.lower()
    if any(keyword in message for keyword in PROJECT_TASK_EXCLUSIONS):
        return False
    if ("项目" in message or "模块" in message or "系统" in message) and not any(
        token in message for token in ("我的", "帮我", "给我", "提醒我", "待办")
    ):
        return False
    if any(keyword in lowered or keyword in message for keyword in TASK_KEYWORDS):
        return True
    explicit_patterns = (
        "帮我创建",
        "帮我新增",
        "帮我添加",
        "帮我记一个",
        "给我记一个",
        "提醒我",
        "列出我的任务",
        "看看我的任务",
        "我的任务",
        "我的待办",
    )
    return any(pattern in message for pattern in explicit_patterns)
