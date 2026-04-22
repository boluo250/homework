from __future__ import annotations

from app.core.http import HttpRequest, HttpResponse
from app.state.file_state import FileState
from app.tools.rag_tool import RagTool


async def handle_files(
    request: HttpRequest,
    repository,
    file_service,
    *,
    file_state: FileState | None = None,
    rag_tool: RagTool | None = None,
) -> HttpResponse:
    file_state = file_state or FileState(repository)
    if request.method == "GET":
        client_id = request.query.get("client_id")
        user_id = request.query.get("user_id")
        file_id = request.query.get("file_id")
        if not user_id and client_id:
            user = await repository.get_or_create_user(client_id)
            user_id = user.id
        if not user_id:
            return HttpResponse.json({"error": "user_id or client_id is required"}, status=400)
        if file_id:
            detail = (
                await rag_tool.get_file_detail(user_id=user_id, file_id=file_id)
                if rag_tool is not None
                else await file_service.get_file_detail_for_user(user_id=user_id, file_id=file_id)
            )
            if not detail:
                return HttpResponse.json({"error": "file not found"}, status=404)
            return HttpResponse.json(detail)
        if rag_tool is not None:
            payload_files = await rag_tool.list_files(user_id)
        else:
            files = await file_state.list_files(user_id)
            payload_files = []
            for item in files:
                payload = item.to_dict()
                payload["vector_count"] = await file_service.get_file_vector_count(user_id=user_id, file_id=item.id)
                payload_files.append(payload)
        return HttpResponse.json({"files": payload_files, "user_id": user_id})

    if request.method == "POST":
        payload = request.json_data or {}
        client_id = str(payload.get("client_id", "")).strip()
        filename = str(payload.get("filename", "")).strip()
        content_type = str(payload.get("content_type", "application/octet-stream")).strip()
        content_base64 = str(payload.get("content_base64", "")).strip()
        if not client_id or not filename or not content_base64:
            return HttpResponse.json(
                {"error": "client_id, filename and content_base64 are required"},
                status=400,
            )
        try:
            if rag_tool is not None:
                result = await rag_tool.index_file(
                    client_id=client_id,
                    filename=filename,
                    content_type=content_type,
                    content_base64=content_base64,
                )
            else:
                result = await file_service.upload_base64_file(
                    client_id=client_id,
                    filename=filename,
                    content_type=content_type,
                    content_base64=content_base64,
                )
        except ValueError as exc:
            return HttpResponse.json({"error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            return HttpResponse.json({"error": f"Upload failed: {exc}"}, status=500)
        return HttpResponse.json(result, status=201)

    if request.method == "DELETE":
        client_id = request.query.get("client_id")
        file_id = request.query.get("file_id")
        if not client_id or not file_id:
            return HttpResponse.json({"error": "client_id and file_id are required"}, status=400)
        try:
            deleted = (
                await rag_tool.delete_file(client_id=client_id, file_id=file_id)
                if rag_tool is not None
                else await file_service.delete_file(client_id=client_id, file_id=file_id)
            )
        except Exception as exc:  # noqa: BLE001
            return HttpResponse.json({"error": f"Delete failed: {exc}"}, status=500)
        if not deleted:
            return HttpResponse.json({"error": "file not found"}, status=404)
        return HttpResponse.json({"deleted": deleted})

    if request.method == "PATCH":
        payload = request.json_data or {}
        client_id = str(payload.get("client_id", "")).strip()
        file_id = str(payload.get("file_id", "")).strip()
        filename = str(payload.get("filename", "")).strip()
        if not client_id or not file_id or not filename:
            return HttpResponse.json({"error": "client_id, file_id and filename are required"}, status=400)
        try:
            renamed = (
                await rag_tool.rename_file(client_id=client_id, file_id=file_id, filename=filename)
                if rag_tool is not None
                else await file_service.rename_file(client_id=client_id, file_id=file_id, filename=filename)
            )
        except ValueError as exc:
            return HttpResponse.json({"error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            return HttpResponse.json({"error": f"Rename failed: {exc}"}, status=500)
        if not renamed:
            return HttpResponse.json({"error": "file not found"}, status=404)
        return HttpResponse.json({"file": renamed})

    return HttpResponse.json({"error": "Method not allowed"}, status=405)
