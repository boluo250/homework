from app.core.models import TaskPriority
from app.core.task_protocol import TaskToolAction, parse_task_tool_call


def test_create_task_protocol_extracts_priority_and_due_at() -> None:
    call = parse_task_tool_call('帮我创建一个"简历优化"任务，下周五前完成，高优先级')
    assert call.action == TaskToolAction.CREATE
    assert call.title == "简历优化"
    assert call.priority == TaskPriority.HIGH
    assert call.due_at == "下周五"


def test_create_task_protocol_extracts_details() -> None:
    call = parse_task_tool_call('帮我创建一个"简历优化"任务，要求突出 Agent、RAG 和 Cloudflare Worker 项目经验，下周五前完成')
    assert call.action == TaskToolAction.CREATE
    assert call.title == "简历优化"
    assert call.details is not None
    assert "Cloudflare Worker" in call.details


def test_get_task_protocol_extracts_title_for_detail_query() -> None:
    call = parse_task_tool_call('看看"简历优化"任务的具体需求')
    assert call.action == TaskToolAction.GET
    assert call.title == "简历优化"
