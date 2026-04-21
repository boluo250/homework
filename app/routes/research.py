from __future__ import annotations

from app.core.http import HttpRequest, HttpResponse


async def handle_research(request: HttpRequest, research_service) -> HttpResponse:
    if request.method == "POST":
        payload = request.json_data or {}
        query = str(payload.get("query", "")).strip()
        client_id = str(payload.get("client_id", "")).strip()
        if not query or not client_id:
            return HttpResponse.json({"error": "query and client_id are required"}, status=400)
        job = await research_service.submit(client_id=client_id, query=query)
        return HttpResponse.json(job, status=202)

    if request.method == "GET":
        job_id = request.query.get("job_id", "").strip()
        if not job_id:
            return HttpResponse.json({"error": "job_id is required"}, status=400)
        job = await research_service.get(job_id)
        if not job:
            return HttpResponse.json({"error": "job not found"}, status=404)
        return HttpResponse.json(job)

    return HttpResponse.json({"error": "Method not allowed"}, status=405)
