"""Text-only PDF extraction and explainable candidate association; never auto-confirm."""

import base64
import re
from io import BytesIO
from uuid import uuid4

from fastapi import HTTPException
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .db import Material, SourceChunk
from .pdf_process import extract_isolated

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_EXTRACTED_CHARS = 1_000_000


def extract_pdf(data):
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF 超过 20 MB 限制")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, "文件不是有效 PDF")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise HTTPException(422, "加密 PDF 不支持导入，请先提供未加密版本")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise HTTPException(413, "PDF 超过 100 页限制")
        pages, chars = [], 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text().strip()
            chars += len(text)
            if chars > MAX_EXTRACTED_CHARS:
                raise HTTPException(413, "PDF 抽取正文超出长度限制")
            if text:
                pages.append({"text": text, "location": f"第 {number} 页"})
        if not pages:
            raise HTTPException(422, "PDF 未包含可抽取文本；扫描件需要先完成 OCR")
        return pages
    except (PdfReadError, ValueError, KeyError, TypeError, RecursionError):
        raise HTTPException(422, "PDF 结构损坏或无法抽取文本") from None


def import_segments(params):
    if params["source_type"] == "pdf":
        return extract_isolated(base64.b64decode(params["pdf_base64"], validate=True)), "pypdf-text"
    if params["source_type"] == "pdf_mock":
        return [
            {
                "text": "栈在同一端入栈和出栈，最后进入的元素最先离开。函数嵌套调用的返回过程符合后进先出。",
                "location": "第 1 页",
            },
            {
                "text": "推演操作时先记下每步栈内容。push(A)、push(B)、pop() 后只剩 A；再次入栈 C 后栈顶为 C。",
                "location": "第 2 页",
            },
        ], "mock-pdf"
    texts = [p.strip() for p in re.split(r"\n\s*\n", params["text"]) if p.strip()]
    return [{"text": text, "location": f"第 {i + 1} 段"} for i, text in enumerate(texts)], "text-split"


def associate(text, nodes, default):
    """Longest literal knowledge name wins; fallback is the selected scope, not an AI claim."""
    matches = [node for node in nodes if node["name"].lower() in text.lower()]
    matches.sort(key=lambda node: (-len(node["name"]), node["id"]))
    return matches[0]["id"] if matches else default


def save_import(db, job, nodes, default):
    segments, implementation = import_segments(job.params)
    return persist_import(db, job, (nodes, default), (segments, implementation))


def persist_import(db, job, context, parsed):
    nodes, default = context
    segments, implementation = parsed
    material = Material(
        id=str(uuid4()),
        user_id=job.user_id,
        title=job.params["title"],
        text="\n\n".join(p["text"] for p in segments),
        knowledge_id=default,
        confirmed=False,
        deleted=False,
    )
    db.add(material)
    db.flush()
    for segment in segments:
        db.add(
            SourceChunk(
                id=str(uuid4()),
                material_id=material.id,
                text=segment["text"],
                knowledge_id=associate(segment["text"], nodes, default),
                status="pending",
                location=segment["location"],
                implementation=implementation + "+name-match-v1",
            )
        )
    job.status = "succeeded"
    job.result = {
        "material_id": material.id,
        "chunk_count": len(segments),
        "implementation": implementation,
        "association": "name-match-v1",
        "requires_confirmation": True,
        "notice": "样例正文，不是实际上传 PDF 的解析结果"
        if implementation == "mock-pdf"
        else "保留原文位置；按知识点名称匹配候选，未匹配时使用所选范围，均需本人确认。",
    }
