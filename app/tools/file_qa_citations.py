from __future__ import annotations

import re

EVIDENCE_IDS_LINE_RE = re.compile(r"(?:^|\n)EVIDENCE_IDS:\s*\[([0-9,\s]*)\]\s*$", re.MULTILINE)


def extract_answer_and_used_evidence_ids(reply: str, *, evidence_count: int) -> tuple[str, list[int]]:
    matches = list(EVIDENCE_IDS_LINE_RE.finditer(reply))
    if not matches:
        return reply.strip(), []
    match = matches[-1]
    ids: list[int] = []
    seen: set[int] = set()
    for raw in match.group(1).split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if value < 1 or value > evidence_count or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    cleaned = (reply[: match.start()] + reply[match.end() :]).strip()
    return cleaned, ids


def append_file_citations(reply: str, rag_hits: list[dict], *, used_evidence_ids: list[int]) -> str:
    citations: list[str] = []
    seen: set[tuple[str, int]] = set()
    for evidence_id in used_evidence_ids:
        if evidence_id < 1 or evidence_id > len(rag_hits):
            continue
        payload = rag_hits[evidence_id - 1].get("payload", {})
        filename = str(payload.get("filename", "unknown"))
        chunk_index = int(payload.get("chunk_index", 0))
        key = (filename, chunk_index)
        if key in seen:
            continue
        seen.add(key)
        citations.append(f"- {filename}#片段{chunk_index}")
    if not citations:
        return reply.strip()
    return reply.rstrip() + "\n\n参考来源：\n" + "\n".join(citations)
