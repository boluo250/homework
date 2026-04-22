from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

# Cloudflare's Python worker loader treats the directory containing the main file
# as the import root, so `app/entry.py` becomes `entry.py` at runtime. Create a
# lightweight `app` package alias in that environment so the existing imports
# continue to work both locally and under `wrangler dev`.
if __package__ in {None, ""} and "app" not in sys.modules:
    package = types.ModuleType("app")
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules["app"] = package

from app.core.http import HttpRequest, HttpResponse
from app.providers.embedding_remote import RemoteEmbeddingProvider
from app.providers.openrouter_chat import OpenRouterChatProvider
from app.routes.admin import handle_admin_reset
from app.routes.chat import handle_chat
from app.routes.files import handle_files
from app.routes.research import handle_research
from app.routes.tasks import handle_tasks
from app.runtime.agent_loop import AgentLoop
from app.services.embedding_service import EmbeddingService
from app.services.cloudflare_d1_repo import CloudflareD1Repository
from app.services.cloudflare_r2_store import CloudflareR2FileStore
from app.services.d1_repo import SQLiteAppRepository
from app.services.file_parser import FileParser
from app.services.file_service import FileService
from app.services.memory_service import MemoryService
from app.services.mistral_document_parse import MistralDocumentParseService
from app.services.openrouter_client import OpenRouterClient
from app.services.qdrant_store import QdrantStore
from app.services.r2_store import R2FileStore
from app.services.rag_service import RagService
from app.services.research_service import ResearchService
from app.services.search_service import SearchService
from app.services.schema_sql import SCHEMA_SQL
from app.services.web_fetch_service import WebFetchService
from app.state.assistant_state import AssistantState
from app.state.conversation_state import ConversationState
from app.state.file_state import FileState
from app.state.research_state import ResearchState
from app.state.task_state import TaskState
from app.state.user_state import UserState
from app.tools.assistant_identity_tool import AssistantIdentityTool
from app.tools.profile_tool import ProfileTool
from app.tools.rag_tool import RagTool
from app.tools.research_tool import ResearchTool
from app.tools.task_tool import TaskTool
from app.tools.workspace_admin_tool import WorkspaceAdminTool
from app.ui_assets import UI_ASSETS

try:
    from workers import Request, Response, WorkerEntrypoint  # type: ignore
except ImportError:  # pragma: no cover
    Request = Any

    class Response:  # pragma: no cover
        def __init__(self, body: bytes | str, status: int = 200, headers: dict[str, str] | None = None) -> None:
            self.body = body
            self.status = status
            self.headers = headers or {}

    class WorkerEntrypoint:  # pragma: no cover
        env: Any


APP_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_DIR.parent
DATA_DIR = WORKSPACE_ROOT / ".taskmate"
_APP_CONTAINER: AppContainer | None = None


class AppContainer:
    def __init__(self, env: Any) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        migrations_path = WORKSPACE_ROOT / "migrations" / "001_init.sql"
        if getattr(env, "DB", None):
            repository = CloudflareD1Repository(env.DB, migrations_sql=SCHEMA_SQL)
        else:
            repository = SQLiteAppRepository(
                db_path=DATA_DIR / "taskmate.db",
                migrations_path=migrations_path,
            )
        embedding_provider = RemoteEmbeddingProvider(
            api_key=getattr(env, "EMBEDDING_API_KEY", None),
            model=getattr(env, "EMBEDDING_MODEL", "text-embedding-3-small"),
            endpoint_url=getattr(env, "EMBEDDING_API_URL", None),
        )
        self.embedding_service = EmbeddingService(embedding_provider)
        chat_provider = OpenRouterChatProvider(
            api_key=getattr(env, "OPENROUTER_API_KEY", None),
            model=getattr(env, "OPENROUTER_MODEL", "openrouter/auto"),
            app_name=getattr(env, "APP_NAME", "TaskMate"),
        )
        self.openrouter_client = OpenRouterClient(chat_provider)
        search_service = SearchService(api_key=getattr(env, "SERPER_API_KEY", None))
        qdrant_remote_url = _resolve_qdrant_remote_url(getattr(env, "QDRANT_URL", None))
        qdrant_store = QdrantStore(
            storage_path=DATA_DIR / "qdrant_document_chunks.json",
            remote_url=qdrant_remote_url,
            api_key=getattr(env, "QDRANT_API_KEY", None),
        )
        rag_service = RagService(
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
        )
        memory_service = MemoryService(
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
        )
        file_store = (
            CloudflareR2FileStore(
                getattr(env, "FILES_BUCKET"),
                bucket_name=getattr(env, "R2_BUCKET_NAME", "taskmate-homework-files"),
            )
            if getattr(env, "FILES_BUCKET", None)
            else R2FileStore(DATA_DIR / "r2", bucket_name=getattr(env, "R2_BUCKET_NAME", None))
        )
        self.repository = repository
        self.user_state = UserState(repository)
        self.assistant_state = AssistantState(repository)
        self.task_state = TaskState(repository)
        self.file_state = FileState(repository)
        self.research_state = ResearchState(repository)
        self.conversation_state = ConversationState(repository)
        self.file_service = FileService(
            repository=repository,
            file_store=file_store,
            file_parser=FileParser(),
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
            pdf_parse_service=MistralDocumentParseService(
                api_key=getattr(env, "MISTRAL_API_KEY", None),
                model=getattr(env, "MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
            ),
        )
        self.research_service = ResearchService(
            repository=repository,
            search_service=search_service,
            web_fetch_service=WebFetchService(),
            chat_provider=chat_provider,
            queue_binding=getattr(env, "RESEARCH_QUEUE", None),
        )
        self.profile_tool = ProfileTool(self.user_state)
        self.assistant_identity_tool = AssistantIdentityTool(self.assistant_state)
        self.task_tool = TaskTool(self.task_state)
        self.rag_tool = RagTool(
            file_state=self.file_state,
            file_service=self.file_service,
            rag_service=rag_service,
            chat_provider=chat_provider,
        )
        self.research_tool = ResearchTool(self.research_state, self.research_service)
        self.workspace_admin_tool = WorkspaceAdminTool(
            repository=repository,
            file_store=file_store,
            qdrant_store=qdrant_store,
            task_state=self.task_state,
            file_state=self.file_state,
            research_state=self.research_state,
            user_state=self.user_state,
        )
        self.agent = AgentLoop(
            repository=repository,
            chat_provider=chat_provider,
            search_service=search_service,
            rag_service=rag_service,
            memory_service=memory_service,
            profile_tool=self.profile_tool,
            assistant_identity_tool=self.assistant_identity_tool,
            task_tool=self.task_tool,
            rag_tool=self.rag_tool,
            research_tool=self.research_tool,
        )


def get_container(env: Any) -> AppContainer:
    global _APP_CONTAINER
    if _APP_CONTAINER is None:
        _APP_CONTAINER = AppContainer(env)
    return _APP_CONTAINER


def _load_asset(filename: str) -> str:
    asset_path = APP_DIR / "ui" / filename
    try:
        return asset_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        asset = UI_ASSETS.get(filename)
        if asset is not None:
            return asset
        raise


def _resolve_qdrant_remote_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    normalized = raw_url.strip()
    if not normalized:
        return None
    if "your-cluster-id" in normalized:
        return None
    return normalized


def _with_cors(response: HttpResponse) -> HttpResponse:
    response.headers.update(
        {
            "access-control-allow-origin": "*",
            "access-control-allow-methods": "GET,POST,DELETE,PATCH,OPTIONS",
            "access-control-allow-headers": "content-type",
        }
    )
    return response


async def route_request(request: HttpRequest, container: AppContainer) -> HttpResponse:
    if request.method == "OPTIONS":
        return _with_cors(HttpResponse(status=204))
    if request.path == "/":
        return HttpResponse.html(_load_asset("index.html"))
    if request.path == "/app.js":
        return HttpResponse(
            status=200,
            headers={"content-type": "application/javascript; charset=utf-8"},
            body=_load_asset("app.js").encode("utf-8"),
        )
    if request.path == "/styles.css":
        return HttpResponse(
            status=200,
            headers={"content-type": "text/css; charset=utf-8"},
            body=_load_asset("styles.css").encode("utf-8"),
        )
    if request.path == "/api/chat":
        return _with_cors(await handle_chat(request, container.agent))
    if request.path == "/api/tasks":
        return _with_cors(
            await handle_tasks(
                request,
                container.repository,
                task_state=getattr(container, "task_state", None),
            )
        )
    if request.path == "/api/files":
        return _with_cors(
            await handle_files(
                request,
                container.repository,
                container.file_service,
                file_state=getattr(container, "file_state", None),
                rag_tool=getattr(container, "rag_tool", None),
            )
        )
    if request.path == "/api/research":
        return _with_cors(
            await handle_research(
                request,
                container.research_service,
                research_tool=getattr(container, "research_tool", None),
            )
        )
    if request.path == "/api/debug/research":
        job_id = request.query.get("job_id", "").strip()
        if not job_id:
            return _with_cors(HttpResponse.json({"error": "job_id required"}, status=400))
        job = await container.repository.get_research_job(job_id)
        state = await container.repository.get_research_job_state(job_id)
        return _with_cors(HttpResponse.json({
            "job": job.to_dict() if job else None,
            "state": state.to_dict() if state else None,
        }))
    if request.path == "/api/admin/reset":
        return _with_cors(
            await handle_admin_reset(
                request,
                container.repository,
                container.file_service.file_store,
                container.file_service.qdrant_store,
                workspace_admin_tool=getattr(container, "workspace_admin_tool", None),
            )
        )
    return _with_cors(HttpResponse.json({"error": "Not found"}, status=404))


class Default(WorkerEntrypoint):
    async def fetch(self, request: Request) -> Response:
        body_bytes = b""
        if hasattr(request, "text"):
            raw_text = await request.text()
            body_bytes = raw_text.encode("utf-8") if raw_text else b""
        headers = dict(getattr(request, "headers", {}) or {})
        http_request = HttpRequest.from_raw(
            method=getattr(request, "method", "GET"),
            url=str(getattr(request, "url", "/")),
            headers=headers,
            body=body_bytes,
        )
        container = get_container(self.env)
        response = await route_request(http_request, container)
        return Response(response.body, status=response.status, headers=response.headers)

    async def queue(self, batch) -> None:
        import traceback as _tb
        container = get_container(self.env)
        print(
            f"[taskmate] {json.dumps({'scope': 'worker.queue', 'event': 'batch.start', 'message_count': len(getattr(batch, 'messages', []) or [])}, ensure_ascii=False)}"
        )
        for message in getattr(batch, "messages", []):
            try:
                print(
                    f"[taskmate] {json.dumps({'scope': 'worker.queue', 'event': 'message.start', 'attempts': getattr(message, 'attempts', None)}, ensure_ascii=False, default=str)}"
                )
                await container.research_service.process_queue_message(message.body)
                print(f"[taskmate] {json.dumps({'scope': 'worker.queue', 'event': 'message.ok'}, ensure_ascii=False)}")
                if hasattr(message, "ack"):
                    message.ack()
            except Exception as exc:  # noqa: BLE001
                _full_error = _tb.format_exc()
                job_id = ""
                body = getattr(message, "body", None)
                if isinstance(body, dict):
                    job_id = str(body.get("job_id", "")).strip()
                elif isinstance(body, str):
                    try:
                        job_id = str(json.loads(body).get("job_id", "")).strip()
                    except Exception:  # noqa: BLE001
                        job_id = ""
                elif body is not None and hasattr(body, "to_py"):
                    try:
                        py_body = body.to_py()
                        if isinstance(py_body, dict):
                            job_id = str(py_body.get("job_id", "")).strip()
                    except Exception:  # noqa: BLE001
                        job_id = ""
                elif body is not None and hasattr(body, "get"):
                    try:
                        job_id = str(body.get("job_id") or "").strip()
                    except Exception:  # noqa: BLE001
                        job_id = ""
                print(
                    f"[taskmate] {json.dumps({'scope': 'worker.queue', 'event': 'message.error', 'job_id': job_id, 'error': str(exc)}, ensure_ascii=False)}"
                )
                if job_id:
                    attempts = int(getattr(message, "attempts", 1) or 1)
                    error_detail = f"{exc}\n\n```\n{_full_error}\n```"
                    if attempts >= 3:
                        await container.research_service.mark_failed(job_id, error_detail)
                        if hasattr(message, "ack"):
                            message.ack()
                    else:
                        await container.research_service.mark_retry(job_id, error_detail)
                        if hasattr(message, "retry"):
                            message.retry()
                elif hasattr(message, "ack"):
                    message.ack()
