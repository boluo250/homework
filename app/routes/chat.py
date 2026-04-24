from __future__ import annotations

import json
from dataclasses import asdict

from app.core.http import HttpRequest, HttpResponse
from app.core.models import ChatRequest


async def handle_chat(request: HttpRequest, agent) -> HttpResponse:
    if request.method == "GET":
        client_id = str(request.query.get("client_id", "")).strip()
        if not client_id:
            return HttpResponse.json({"error": "client_id is required"}, status=400)
        session_meta = await agent.get_session_meta(client_id)
        return HttpResponse.json(
            {
                "user_profile": asdict(session_meta["user_profile"]),
                "assistant_name": session_meta["assistant_name"],
            }
        )
    if request.method != "POST":
        return HttpResponse.json({"error": "Method not allowed"}, status=405)
    chat_request = _build_chat_request(request)
    if chat_request is None:
        return HttpResponse.json({"error": "client_id and message are required"}, status=400)
    response = await agent.handle_chat(chat_request)
    return HttpResponse.json(response.to_dict())


async def handle_chat_stream(request: HttpRequest, agent) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse.json({"error": "Method not allowed"}, status=405)
    chat_request = _build_chat_request(request)
    if chat_request is None:
        return HttpResponse.json({"error": "client_id and message are required"}, status=400)
    if hasattr(agent, "stream_chat_events"):
        return HttpResponse.sse_stream(_stream_agent_events(agent, chat_request))

    events = [_sse_event("status", {"label": _stream_status_label(chat_request.message)})]
    response = await agent.handle_chat(chat_request)
    payload = response.to_dict()
    events.append(_sse_event("meta", _build_meta_payload(payload)))
    for chunk in _split_stream_text(payload["reply"]):
        events.append(_sse_event("delta", {"text": chunk}))
    events.append(_sse_event("done", payload))
    return HttpResponse.sse(events)


def _build_chat_request(request: HttpRequest) -> ChatRequest | None:
    payload = request.json_data or {}
    message = str(payload.get("message", "")).strip()
    client_id = str(payload.get("client_id", "")).strip()
    if not message or not client_id:
        return None
    file_ids = payload.get("file_ids", [])
    return ChatRequest(
        client_id=client_id,
        message=message,
        conversation_id=payload.get("conversation_id"),
        file_ids=list(file_ids) if isinstance(file_ids, list) else [],
    )


def _sse_event(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


async def _stream_agent_events(agent, chat_request: ChatRequest):
    async for event_name, payload in agent.stream_chat_events(chat_request):
        yield _sse_event(event_name, payload)


def _build_meta_payload(payload: dict) -> dict:
    return {
        "conversation_id": payload["conversation_id"],
        "intent": payload["intent"],
        "assistant_name": payload.get("assistant_name"),
        "user_profile": payload.get("user_profile"),
    }


def _split_stream_text(text: str, *, chunk_size: int = 24) -> list[str]:
    normalized = text or ""
    if not normalized:
        return []
    return [normalized[index : index + chunk_size] for index in range(0, len(normalized), chunk_size)]


def _stream_status_label(message: str) -> str:
    lowered = message.lower()
    if any(token in message for token in ("文档", "文件", "pdf", "docx", "总结", "概括", "归纳")):
        return "正在整理文件内容"
    if any(token in message for token in ("研究", "调研", "对比", "方案", "报告", "分析")):
        return "正在准备研究计划"
    if any(token in message for token in ("我的任务", "我的待办", "待办", "提醒我", "帮我创建", "给我记")) or "todo" in lowered:
        return "正在处理任务请求"
    return "正在思考"
