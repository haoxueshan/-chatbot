from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document as LangDocument


class DocumentParseError(ValueError):
    pass


@dataclass
class ParsedDocument:
    chunks: list[LangDocument]
    page_count: int
    warnings: list[str]


def _safe_office(data: bytes):
    if not data.startswith(b"PK"):
        raise DocumentParseError("文件内容不是有效的 Office Open XML 格式。")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(i.file_size for i in entries) > 200 * 1024 * 1024:
            raise DocumentParseError("文档解压后过大，拒绝解析。")
        if any(i.file_size > 50 * 1024 * 1024 or (i.compress_size and i.file_size / i.compress_size > 1000) for i in entries):
            raise DocumentParseError("文档压缩比例异常，拒绝解析。")


def _chunk(text: str, page: int | None, location: str, position=0):
    text = text.strip()
    output = []
    start = 0
    while start < len(text):
        end = min(start + 900, len(text))
        if end < len(text):
            boundary = max(text.rfind("。", start + 400, end), text.rfind("\n", start + 400, end), text.rfind(". ", start + 400, end))
            if boundary > start:
                end = boundary + 1
        output.append(LangDocument(page_content=text[start:end], metadata={"page": page, "position": position + start, "end_position": position + end, "location": location}))
        if end == len(text):
            break
        start = max(start + 1, end - 100)
    return output


def parse_document(name: str, data: bytes) -> ParsedDocument:
    extension = Path(name).suffix.lower()
    chunks, warnings = [], []
    if extension == ".pdf":
        if not data.startswith(b"%PDF"):
            raise DocumentParseError("文件扩展名为 PDF，但内容不是 PDF。")
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentParseError("加密 PDF 无法解析，请先提供未加密版本。")
        if len(reader.pages) > 1000:
            raise DocumentParseError("文档超过 1000 页应用上限。")
        for page, item in enumerate(reader.pages, 1):
            text = item.extract_text() or ""
            if not text.strip():
                warnings.append(f"第 {page} 页无法提取文字，可能是扫描件；本版未启用 OCR。")
            chunks.extend(_chunk(text, page, f"第 {page} 页"))
        count = len(reader.pages)
    elif extension == ".pptx":
        _safe_office(data)
        from pptx import Presentation
        deck = Presentation(io.BytesIO(data))
        if len(deck.slides) > 1000:
            raise DocumentParseError("幻灯片超过 1000 页应用上限。")
        for page, slide in enumerate(deck.slides, 1):
            values = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    values.append(shape.text)
                if getattr(shape, "has_table", False):
                    values.extend(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
            text = "\n".join(values)
            if not text.strip():
                warnings.append(f"幻灯片 {page} 无可提取文字；图表、图片及手写文字未做 OCR。")
            chunks.extend(_chunk(text, page, f"幻灯片 {page}"))
        count = len(deck.slides)
    elif extension == ".docx":
        _safe_office(data)
        from docx import Document
        doc = Document(io.BytesIO(data))
        position = 0
        for index, paragraph in enumerate(doc.paragraphs, 1):
            chunks.extend(_chunk(paragraph.text, None, f"段落 {index}", position))
            position += len(paragraph.text) + 1
        for index, table in enumerate(doc.tables, 1):
            text = "\n".join(" | ".join(cell.text for cell in row.cells) for row in table.rows)
            chunks.extend(_chunk(text, None, f"表格 {index}", position))
            position += len(text) + 1
        count = 0
        warnings.append("DOCX 没有固定分页；引用使用段落/表格和字符位置，不伪造页码。图片未做 OCR。")
    else:
        raise DocumentParseError("只支持 PDF、PPTX、DOCX。")
    if not chunks:
        raise DocumentParseError("未提取到可索引文字；可能是扫描件、图片文档或空文档。本版未启用 OCR。")
    if len(chunks) > 5000:
        raise DocumentParseError("文档文本超过 5000 分块应用上限。")
    return ParsedDocument(chunks, count, warnings)
