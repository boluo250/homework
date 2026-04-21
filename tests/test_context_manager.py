from app.core.context import ConversationContextManager
from app.core.models import ConversationMessage, MessageRole


def test_context_manager_keeps_recent_buffer_and_generates_summary() -> None:
    manager = ConversationContextManager(recent_limit=3, summary_trigger=4)
    messages = [
        ConversationMessage(id=f"m{i}", conversation_id="c1", role=MessageRole.USER, content=f"message {i}")
        for i in range(5)
    ]
    bundle = manager.build(messages)
    assert bundle.should_refresh_summary is True
    assert len(bundle.recent_lines) == 3
    assert bundle.summary_text is not None
