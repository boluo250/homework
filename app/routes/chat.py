from __future__ import annotations

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
    payload = request.json_data or {}
    message = str(payload.get("message", "")).strip()
    client_id = str(payload.get("client_id", "")).strip()
    if not message or not client_id:
        return HttpResponse.json(
            {"error": "client_id and message are required"},
            status=400,
        )
    response = await agent.handle_chat(
        ChatRequest(
            client_id=client_id,
            message=message,
            conversation_id=payload.get("conversation_id"),
            file_ids=list(payload.get("file_ids", [])),
        )
    )
    return HttpResponse.json(response.to_dict())
