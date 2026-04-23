from app.core.models import TaskPriority
from app.core.task_protocol import TaskToolAction, parse_task_tool_call


def test_create_task_protocol_extracts_priority_and_schedule() -> None:
    call = parse_task_tool_call('帮我创建一个"简历优化"任务，开始日期 2026-04-24，结束日期 2026-04-30，高优先级')
    assert call.action == TaskToolAction.CREATE
    assert call.title == "简历优化"
    assert call.priority == TaskPriority.HIGH
    assert call.start_at == "2026-04-24"
    assert call.end_at == "2026-04-30"
    assert call.due_at == "2026-04-30"


def test_create_task_protocol_extracts_details() -> None:
    call = parse_task_tool_call('帮我创建一个"简历优化"任务，要求突出 Agent、RAG 和 Cloudflare Worker 项目经验，开始日期 2026-04-24，结束日期 2026-04-30')
    assert call.action == TaskToolAction.CREATE
    assert call.title == "简历优化"
    assert call.details is not None
    assert "Cloudflare Worker" in call.details


def test_get_task_protocol_extracts_title_for_detail_query() -> None:
    call = parse_task_tool_call('看看"简历优化"任务的具体需求')
    assert call.action == TaskToolAction.GET
    assert call.title == "简历优化"


def test_create_task_protocol_does_not_treat_generic_quantifier_as_title() -> None:
    call = parse_task_tool_call("帮我创建个任务")
    assert call.action == TaskToolAction.CREATE
    assert call.title is None


def test_task_protocol_does_not_treat_feature_description_as_create_command() -> None:
    call = parse_task_tool_call("创建任务时，需要补充开始日期和结束日期")
    assert call.action == TaskToolAction.LIST
