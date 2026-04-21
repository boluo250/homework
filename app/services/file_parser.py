from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path


class FileParser:
    SUPPORTED_TYPES = {".txt", ".md", ".pdf", ".docx", ".png", ".jpg", ".jpeg"}
    SHORT_DOC_MAX_CHARS = 3000
    MEDIUM_DOC_MAX_CHARS = 12000
    STRUCTURED_DOC_KEYWORDS = {
        "resume",
        "cv",
        "job description",
        "jd",
        "简历",
        "个人信息",
        "工作经历",
        "项目经历",
        "教育背景",
        "专业技能",
        "技能",
        "experience",
        "education",
        "skills",
    }

    def parse_text(self, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {suffix}")
        if suffix in {".txt", ".md"}:
            return content.decode("utf-8")
        if suffix == ".docx":
            return self._parse_docx(content)
        if suffix == ".pdf":
            return self._parse_pdf(content)
        raise ValueError(f"Unsupported file type: {suffix}")

    def chunk_document(self, filename: str, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []
        if len(normalized) <= self.SHORT_DOC_MAX_CHARS:
            return [normalized]
        if self._is_structured_document(filename, normalized):
            chunks = self._chunk_by_structure(normalized, target_chunk_size=1500, max_chunk_size=2200)
            if chunks:
                return chunks
        if len(normalized) <= self.MEDIUM_DOC_MAX_CHARS:
            chunks = self._chunk_by_structure(normalized, target_chunk_size=1200, max_chunk_size=1800)
            if chunks:
                return chunks
        return self.chunk_text(normalized, chunk_size=1400, overlap=180)

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
        chunks: list[str] = []
        cursor = 0
        normalized = self._normalize_text(text)
        while cursor < len(normalized):
            end = min(len(normalized), cursor + chunk_size)
            chunk = normalized[cursor:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == len(normalized):
                break
            cursor = max(end - overlap, cursor + 1)
        return chunks

    def _parse_docx(self, content: bytes) -> str:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        return re.sub(r"\n{3,}", "\n\n", xml).strip()

    def _parse_pdf(self, content: bytes) -> str:
        _ = content
        raise ValueError("PDF parsing is handled by the external document parsing service.")

    def _normalize_text(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _is_structured_document(self, filename: str, text: str) -> bool:
        lowered_name = Path(filename).stem.lower().replace("-", " ").replace("_", " ")
        if any(keyword in lowered_name for keyword in {"resume", "cv", "jd", "job description", "简历", "职位"}):
            return True
        lowered_text = text.lower()
        matched = 0
        for keyword in self.STRUCTURED_DOC_KEYWORDS:
            if keyword in lowered_text:
                matched += 1
            if matched >= 2:
                return True
        return False

    def _chunk_by_structure(
        self,
        text: str,
        *,
        target_chunk_size: int,
        max_chunk_size: int,
    ) -> list[str]:
        sections = self._split_sections(text)
        if not sections:
            return []

        chunks: list[str] = []
        current: list[str] = []
        current_length = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue
            if len(section) > max_chunk_size:
                if current:
                    chunks.append("\n\n".join(current).strip())
                    current = []
                    current_length = 0
                chunks.extend(self.chunk_text(section, chunk_size=max_chunk_size, overlap=120))
                continue

            next_length = current_length + len(section) + (2 if current else 0)
            if current and next_length > max_chunk_size:
                chunks.append("\n\n".join(current).strip())
                current = [section]
                current_length = len(section)
                continue

            current.append(section)
            current_length = next_length
            if current_length >= target_chunk_size:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_length = 0

        if current:
            chunks.append("\n\n".join(current).strip())

        return [chunk for chunk in chunks if chunk]

    def _split_sections(self, text: str) -> list[str]:
        paragraph_sections = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
        if len(paragraph_sections) > 1:
            return paragraph_sections

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        sections: list[str] = []
        current: list[str] = []
        for line in lines:
            if current and self._looks_like_heading(line):
                sections.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current).strip())
        return sections

    def _looks_like_heading(self, line: str) -> bool:
        lowered = line.lower()
        if len(line) > 40:
            return False
        if any(keyword in lowered for keyword in self.STRUCTURED_DOC_KEYWORDS):
            return True
        return bool(re.match(r"^(第[一二三四五六七八九十]+|[0-9]+[.)、]|[A-Z][.)])", line))
