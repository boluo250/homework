from app.providers.openrouter_chat import OpenRouterChatProvider


def test_extract_text_ignores_none_content() -> None:
    provider = OpenRouterChatProvider()
    assert provider._extract_text({"content": None}) == ""


def test_extract_text_reads_text_from_content_array() -> None:
    provider = OpenRouterChatProvider()
    payload = {"content": [{"type": "text", "text": "归纳后的回答"}]}
    assert provider._extract_text(payload) == "归纳后的回答"


def test_extract_text_falls_back_to_reasoning() -> None:
    provider = OpenRouterChatProvider()
    payload = {"content": None, "reasoning": "这是模型给出的实际文本"}
    assert provider._extract_text(payload) == "这是模型给出的实际文本"


def test_finalize_text_marks_length_truncation() -> None:
    provider = OpenRouterChatProvider()
    text = provider._finalize_text("这是回答", {"finish_reason": "length"})
    assert "输出长度限制" in text
