from datetime import date

from app.core.models import PendingTaskDraftRecord
from app.core.task_slot_extractor import TaskSlotExtractor
from app.providers.llm_base import ChatProviderBase


class StaticJsonProvider(ChatProviderBase):
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        _ = system_prompt
        _ = user_message
        return self.payload


def test_task_slot_extractor_normalizes_dotted_dates() -> None:
    async def run() -> None:
        extractor = TaskSlotExtractor(
            StaticJsonProvider(
                """
                {
                  "title": "面试作业",
                  "title_source": "current_message",
                  "details": null,
                  "details_source": "none",
                  "priority": "high",
                  "priority_source": "current_message",
                  "start_at_raw": "2026.4.1.",
                  "start_at_source": "current_message",
                  "end_at_raw": "2026.4.30",
                  "end_at_source": "current_message"
                }
                """
            )
        )
        result = await extractor.extract(
            message="帮我创建面试作业，开始 2026.4.1. 结束 2026.4.30",
            pending_task_draft=None,
            recent_task_titles=[],
            today=date(2026, 4, 24),
            timezone_name="Asia/Shanghai",
            history_lines=[],
        )
        assert result is not None
        assert result.start_at == "2026-04-01"
        assert result.end_at == "2026-04-30"

    __import__("asyncio").run(run())


def test_task_slot_extractor_normalizes_relative_dates() -> None:
    async def run() -> None:
        extractor = TaskSlotExtractor(
            StaticJsonProvider(
                """
                {
                  "title": "周报",
                  "title_source": "current_message",
                  "details": null,
                  "details_source": "none",
                  "priority": null,
                  "priority_source": "none",
                  "start_at_raw": "下周一",
                  "start_at_source": "current_message",
                  "end_at_raw": "月底前",
                  "end_at_source": "current_message"
                }
                """
            )
        )
        result = await extractor.extract(
            message="帮我创建周报，下周一开始，月底前完成",
            pending_task_draft=None,
            recent_task_titles=[],
            today=date(2026, 4, 24),
            timezone_name="Asia/Shanghai",
            history_lines=[],
        )
        assert result is not None
        assert result.start_at == "2026-04-27"
        assert result.end_at == "2026-04-30"

    __import__("asyncio").run(run())


def test_task_slot_extractor_can_fill_title_from_current_message_only() -> None:
    async def run() -> None:
        extractor = TaskSlotExtractor(
            StaticJsonProvider(
                """
                {
                  "title": "给二蛋发邮件",
                  "title_source": "current_message",
                  "details": null,
                  "details_source": "none",
                  "priority": "high",
                  "priority_source": "pending_draft",
                  "start_at_raw": null,
                  "start_at_source": "pending_draft",
                  "end_at_raw": null,
                  "end_at_source": "pending_draft"
                }
                """
            )
        )
        result = await extractor.extract(
            message="给二蛋发邮件",
            pending_task_draft=PendingTaskDraftRecord(
                conversation_id="conv_1",
                priority="high",
                start_at="2026-03-22",
                end_at="2026-04-25",
                missing_fields=["title"],
            ),
            recent_task_titles=["周报"],
            today=date(2026, 4, 24),
            timezone_name="Asia/Shanghai",
            history_lines=["assistant: 这个任务想叫什么？"],
        )
        assert result is not None
        assert result.title == "给二蛋发邮件"
        assert result.start_at == "2026-03-22"
        assert result.end_at == "2026-04-25"

    __import__("asyncio").run(run())


def test_task_slot_extractor_blocks_history_only_dates() -> None:
    async def run() -> None:
        extractor = TaskSlotExtractor(
            StaticJsonProvider(
                """
                {
                  "title": "给二蛋发邮件",
                  "title_source": "current_message",
                  "details": null,
                  "details_source": "none",
                  "priority": null,
                  "priority_source": "none",
                  "start_at_raw": "2026-04-20",
                  "start_at_source": "history_context",
                  "end_at_raw": "2026-04-21",
                  "end_at_source": "history_context"
                }
                """
            )
        )
        result = await extractor.extract(
            message="给二蛋发邮件",
            pending_task_draft=None,
            recent_task_titles=["周报"],
            today=date(2026, 4, 24),
            timezone_name="Asia/Shanghai",
            history_lines=['user: 帮我创建一个"周报"任务，开始日期 2026-04-20，结束日期 2026-04-21'],
        )
        assert result is not None
        assert result.start_at is None
        assert result.end_at is None
        assert result.start_at_source == "none"
        assert result.end_at_source == "none"

    __import__("asyncio").run(run())
