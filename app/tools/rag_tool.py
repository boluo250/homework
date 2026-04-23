from __future__ import annotations

import re

from app.core.models import ToolResult
from app.providers.llm_base import ChatProviderBase
from app.runtime.prompt_builder import build_file_qa_prompt_bundle
from app.services.file_service import FileService
from app.services.rag_service import RagService
from app.state.file_state import FileState
from app.tools.base import ToolOutcome
from app.tools.file_qa_citations import append_file_citations, extract_answer_and_used_evidence_ids


class RagTool:
    def __init__(
        self,
        *,
        file_state: FileState,
        file_service: FileService,
        rag_service: RagService,
        chat_provider: ChatProviderBase,
    ) -> None:
        self.file_state = file_state
        self.file_service = file_service
        self.rag_service = rag_service
        self.chat_provider = chat_provider

    async def index_file(
        self,
        *,
        client_id: str,
        filename: str,
        content_type: str,
        content_base64: str,
    ) -> dict:
        return await self.file_service.upload_base64_file(
            client_id=client_id,
            filename=filename,
            content_type=content_type,
            content_base64=content_base64,
        )

    async def list_files(self, user_id: str) -> list[dict]:
        files = await self.file_state.list_files(user_id)
        payload = []
        for item in files:
            serialized = item.to_dict()
            serialized["vector_count"] = await self.file_service.get_file_vector_count(user_id=user_id, file_id=item.id)
            payload.append(serialized)
        return payload

    async def get_file_detail(self, *, user_id: str, file_id: str) -> dict | None:
        return await self.file_service.get_file_detail_for_user(user_id=user_id, file_id=file_id)

    async def rename_file(self, *, client_id: str, file_id: str, filename: str) -> dict | None:
        return await self.file_service.rename_file(client_id=client_id, file_id=file_id, filename=filename)

    async def delete_file(self, *, client_id: str, file_id: str) -> dict | None:
        return await self.file_service.delete_file(client_id=client_id, file_id=file_id)

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        file_ids: list[str] | None = None,
        limit: int = 6,
    ) -> list[dict]:
        return await self.rag_service.retrieve(user_id=user_id, query=query, file_ids=file_ids, limit=limit)

    async def answer(
        self,
        *,
        user_id: str,
        message: str,
        file_ids: list[str] | None,
        answer_mode: str | None = None,
    ) -> ToolOutcome:
        rag_hits = await self.search(user_id=user_id, query=message, file_ids=file_ids, limit=6)
        tool_results = [ToolResult(name="file_qa", ok=True, content=rag_hits)]
        if not rag_hits:
            return ToolOutcome(
                reply="文件问答链路已经接好接口，但当前还没有可用的向量检索结果。",
                tool_results=tool_results,
            )

        all_files = await self.file_state.list_files(user_id)
        selected_files = [item for item in all_files if not file_ids or item.id in file_ids]
        file_descriptions = []
        for item in selected_files[:3]:
            summary = (item.summary or "").strip()
            file_descriptions.append(f"- {item.filename}: {summary[:180] if summary else '暂无摘要'}")

        evidence_blocks = []
        total_chars = 0
        question_mode = answer_mode or _infer_document_qa_mode(message)
        full_document_context = await self._build_selected_document_context(
            user_id=user_id,
            selected_files=selected_files,
            question_mode=question_mode,
        )
        for index, hit in enumerate(rag_hits, start=1):
            snippet = str(hit.get("text", "")).strip()
            if not snippet:
                continue
            snippet = re.sub(r"\n{3,}", "\n\n", snippet)[:900]
            block = (
                f"[片段 {index}] "
                f"filename={hit.get('payload', {}).get('filename', 'unknown')} "
                f"chunk_index={hit.get('payload', {}).get('chunk_index', 'n/a')} "
                f"score={float(hit.get('score', 0.0)):.3f}\n{snippet}"
            )
            if total_chars + len(block) > 5000 and evidence_blocks:
                break
            evidence_blocks.append(block)
            total_chars += len(block)

        system_prompt, user_prompt = build_file_qa_prompt_bundle(
            question=message,
            question_mode=question_mode,
            file_descriptions=file_descriptions,
            full_document_context=full_document_context,
            evidence_blocks=evidence_blocks,
        )
        reply = await self.chat_provider.chat(system_prompt=system_prompt, user_message=user_prompt)
        used_evidence_ids: list[int] = []
        if _looks_like_provider_failure(reply):
            reply = _fallback_file_qa_reply(message, rag_hits)
            used_evidence_ids = list(range(1, min(len(rag_hits), 4) + 1))
        else:
            reply, used_evidence_ids = extract_answer_and_used_evidence_ids(reply, evidence_count=len(evidence_blocks))
        return ToolOutcome(
            reply=append_file_citations(reply, rag_hits, used_evidence_ids=used_evidence_ids),
            tool_results=tool_results,
        )

    async def _build_selected_document_context(
        self,
        *,
        user_id: str,
        selected_files: list,
        question_mode: str,
    ) -> str:
        if not selected_files or len(selected_files) > 2:
            return ""
        if question_mode not in {"summary", "overview", "compare"}:
            return ""
        sections: list[str] = []
        total_chars = 0
        for item in selected_files:
            chunks = await self.rag_service.qdrant_store.list_chunks_by_file(user_id=user_id, file_id=item.id, limit=24)
            if not chunks:
                continue
            ordered_parts = []
            for chunk in chunks:
                payload = chunk.get("payload", {})
                text = str(payload.get("text", "")).strip()
                if not text:
                    continue
                if total_chars + len(text) > 12000 and sections:
                    break
                ordered_parts.append(text)
                total_chars += len(text)
            if ordered_parts:
                sections.append(f"[文档] {item.filename}\n" + "\n\n".join(ordered_parts))
            if total_chars >= 12000:
                break
        return "\n\n".join(sections).strip()
def _looks_like_provider_failure(reply: str) -> bool:
    lowered = reply.strip().lower()
    return lowered.startswith("openrouter provider is not configured") or lowered.startswith("openrouter request failed")


def _fallback_file_qa_reply(message: str, rag_hits: list[dict]) -> str:
    snippets = []
    for hit in rag_hits[:4]:
        snippet = str(hit.get("text", "")).strip()
        if not snippet:
            continue
        snippets.append(re.sub(r"\s+", " ", snippet)[:220])
    if not snippets:
        return "我暂时没有从文件里提取到足够证据，没法可靠回答这个问题。"
    if _infer_document_qa_mode(message) in {"summary", "overview"}:
        lines = ["我先根据已检索到的文件内容做一个简要总结：", "", "1. 这份材料的核心内容主要集中在以下几点："]
        lines.extend(f"- {item}" for item in snippets[:3])
        lines.append("")
        lines.append("如果你愿意，我可以继续把它整理成更完整的文档摘要、问答卡片或结构化要点。")
        return "\n".join(lines)
    return "我从文件中检索到的关键信息有：\n" + "\n".join(f"- {item}" for item in snippets)


def _infer_document_qa_mode(message: str) -> str:
    lowered = message.lower()
    if any(keyword in lowered for keyword in ["对比", "比较", "区别", "compare", "comparison", "vs"]):
        return "compare"
    if any(keyword in lowered for keyword in ["提取", "列出", "清单", "字段", "表格", "extract", "list", "fields"]):
        return "extract"
    if any(
        keyword in lowered
        for keyword in ["介绍", "总结", "概括", "归纳", "评价", "分析", "介绍下", "summarize", "summary", "introduce", "overview", "analyze", "review"]
    ):
        return "summary"
    if any(keyword in lowered for keyword in ["是什么", "为什么", "如何", "多少", "who", "what", "why", "how"]):
        return "qa"
    return "overview"


def _build_document_qa_instruction(question_mode: str) -> str:
    common = "请基于上面的文件证据直接回答。不要只摘抄原文，要先理解再表达。"
    if question_mode == "summary":
        return common + "这是总结类问题，请先给出整体概括，再整理关键要点，并补一句结论或判断。"
    if question_mode == "compare":
        return common + "这是对比类问题，请先给出总体结论，再按维度比较相同点、不同点和适用场景。"
    if question_mode == "extract":
        return common + "这是信息抽取类问题，请按清单或小标题输出，尽量结构化，缺失项明确标注。"
    if question_mode == "qa":
        return common + "这是具体问答，请先直接回答，再补充对应证据或依据。"
    return common + "这是文档介绍/综述类问题，请优先输出完整且通顺的说明，再补充关键点。"
