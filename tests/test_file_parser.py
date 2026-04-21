from io import BytesIO
from zipfile import ZipFile

from app.services.file_parser import FileParser


def test_docx_parser_extracts_text() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:body><w:p><w:r><w:t>Hello TaskMate</w:t></w:r></w:p></w:body></w:document>",
        )
    parser = FileParser()
    text = parser.parse_text("demo.docx", buffer.getvalue())
    assert "Hello TaskMate" in text


def test_chunk_text_generates_multiple_chunks() -> None:
    parser = FileParser()
    chunks = parser.chunk_text("a" * 900, chunk_size=300, overlap=50)
    assert len(chunks) >= 3


def test_chunk_document_keeps_short_text_as_single_chunk() -> None:
    parser = FileParser()
    chunks = parser.chunk_document("resume.pdf", "姓名：小李\n技能：Python\n项目经历：TaskMate")
    assert chunks == ["姓名：小李\n技能：Python\n项目经历：TaskMate"]


def test_chunk_document_prefers_structured_sections_for_resume_like_text() -> None:
    parser = FileParser()
    text = (
        "个人信息\n"
        + ("姓名：小李 目标岗位：AI 产品经理\n" * 40)
        + "\n\n工作经历\n"
        + ("负责智能体平台设计与交付，推动跨部门协作。\n" * 65)
        + "\n\n项目经历\n"
        + ("主导 RAG 检索、向量入库、文档解析与上线发布。\n" * 65)
        + "\n\n教育背景\n"
        + ("计算机科学与技术，本科。\n" * 30)
    )
    chunks = parser.chunk_document("候选人简历.pdf", text)
    assert len(chunks) >= 2
    assert any("工作经历" in chunk for chunk in chunks)
    assert all(len(chunk) <= 2200 for chunk in chunks)


def test_chunk_document_uses_larger_chunks_for_medium_documents() -> None:
    parser = FileParser()
    paragraph = "TaskMate supports file upload, semantic search, and research workflows. " * 18
    text = "\n\n".join([paragraph for _ in range(8)])
    chunks = parser.chunk_document("architecture.md", text)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 1800 for chunk in chunks)
