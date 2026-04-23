import asyncio

from app.core.intent_interpreter import LLMIntentInterpreter
from app.core.models import Intent, UserProfile
from app.providers.llm_base import ChatProviderBase


class InvalidJsonProvider(ChatProviderBase):
    async def chat(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> str:
        _ = system_prompt
        _ = user_message
        return "not-json"


def test_interpreter_marks_file_inventory_requests() -> None:
    async def run() -> None:
        interpreter = LLMIntentInterpreter(InvalidJsonProvider())
        result = await interpreter.interpret(
            message="数据库里有哪些文档？",
            user=UserProfile(id="u1", client_id="c1"),
            assistant_name="TaskMate",
            recent_lines=[],
            tasks=[],
            file_ids=[],
        )
        assert result.primary_intent == Intent.FILE_QA
        assert result.file_action == "inventory"
        assert result.file_answer_mode is None

    asyncio.run(run())


def test_interpreter_marks_selected_file_compare_mode() -> None:
    async def run() -> None:
        interpreter = LLMIntentInterpreter(InvalidJsonProvider())
        result = await interpreter.interpret(
            message="对比一下这个文档里的两个方案",
            user=UserProfile(id="u2", client_id="c2"),
            assistant_name="TaskMate",
            recent_lines=[],
            tasks=[],
            file_ids=["file_123"],
        )
        assert result.primary_intent == Intent.FILE_QA
        assert result.file_action == "answer"
        assert result.file_answer_mode == "compare"

    asyncio.run(run())


def test_interpreter_does_not_treat_project_task_discussion_as_user_todo() -> None:
    async def run() -> None:
        interpreter = LLMIntentInterpreter(InvalidJsonProvider())
        result = await interpreter.interpret(
            message="这个项目的任务拆解应该怎么设计？",
            user=UserProfile(id="u3", client_id="c3"),
            assistant_name="TaskMate",
            recent_lines=[],
            tasks=[],
            file_ids=[],
        )
        assert result.primary_intent == Intent.GENERAL_CHAT

    asyncio.run(run())
