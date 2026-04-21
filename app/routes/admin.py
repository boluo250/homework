from __future__ import annotations

from app.core.http import HttpRequest, HttpResponse


async def handle_admin_reset(request: HttpRequest, repository, file_store, qdrant_store) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse.json({"error": "Method not allowed"}, status=405)

    payload = request.json_data or {}
    if str(payload.get("confirm", "")).strip() != "RESET_ALL_DATA":
        return HttpResponse.json({"error": "confirm must equal RESET_ALL_DATA"}, status=400)

    await repository.reset_all_data()
    deleted_r2_count = 0
    if hasattr(file_store, "delete_all_files"):
        result = await file_store.delete_all_files()
        deleted_r2_count = int(result or 0)
    await qdrant_store.reset_collection()
    return HttpResponse.json(
        {
            "ok": True,
            "deleted_r2_count": deleted_r2_count,
            "message": "All D1, R2, and Qdrant data has been cleared.",
        }
    )
