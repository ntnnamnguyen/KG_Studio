"""Xử lý đọc DOCX/PDF/TXT và chia đoạn văn bản (Chunking) độc lập 100%."""
from __future__ import annotations

import io
import unicodedata
from pathlib import Path

from shared.config_loader import CONFIG
from shared.text_utils import now_iso, safe_filename, sha, uid

MAX_FILE_BYTES = CONFIG["limits"]["max_file_mb"] * 1024 * 1024
DEFAULT_CHUNK_SIZE = CONFIG["extraction"]["chunk_size"]
DEFAULT_CHUNK_OVERLAP = CONFIG["extraction"]["overlap"]
SUPPORTED_SUFFIXES = (".docx", ".pdf", ".txt")
MIN_TEXT_CHARS = 15
_BOUNDARY_SEPARATORS = ("\n\n", "\n", ". ", "; ", ", ")


def page_at(pages: list[dict] | None, pos: int) -> int | None:
    current = None
    for page in pages or []:
        if page.get("start", 0) <= pos:
            current = page.get("page")
        else:
            break
    return current


def document_payload(file_name: str, binary: bytes) -> dict:
    suffix = Path(str(file_name)).suffix.lower()
    stream = io.BytesIO(binary)
    warnings: list[str] = []

    if suffix == ".txt":
        text = unicodedata.normalize("NFC", binary.decode("utf-8-sig", errors="replace"))
        if "\ufffd" in text:
            warnings.append("Tệp có ký tự không giải mã được bằng UTF-8.")
        return {"text": text.strip(), "pages": [], "warnings": warnings}

    if suffix == ".docx":
        from docx import Document

        doc = Document(stream)
        out = [unicodedata.normalize("NFC", p.text.strip()) for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                line = " | ".join(unicodedata.normalize("NFC", cell.text.strip()) for cell in row.cells)
                if line.strip(" |"):
                    out.append(line)
        return {"text": "\n".join(out), "pages": [], "warnings": warnings}

    if suffix == ".pdf":
        from pypdf import PdfReader

        pdf = PdfReader(stream)
        parts: list[str] = []
        pages: list[dict] = []
        pos = 0
        empty_pages = 0
        for index, page in enumerate(pdf.pages):
            page_text = unicodedata.normalize("NFC", (page.extract_text() or "").strip())
            if not page_text:
                empty_pages += 1
            if index:
                parts.append("\n")
                pos += 1
            pages.append({"page": index + 1, "start": pos})
            marker = f"[Trang {index + 1}]\n"
            parts.append(marker)
            pos += len(marker)
            parts.append(page_text)
            pos += len(page_text)
        if empty_pages:
            warnings.append(f"{empty_pages} trang PDF không có lớp văn bản.")
        return {"text": "".join(parts).strip(), "pages": pages, "warnings": warnings}

    raise ValueError("Chỉ hỗ trợ .docx, .pdf có lớp văn bản, .txt")


def add_document(
    project: dict,
    name: str,
    data: bytes,
    place_scope: str = "",
    source_label: str = "",
) -> tuple[bool, str]:
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("Dữ liệu tệp không hợp lệ")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"Tệp vượt giới hạn {MAX_FILE_BYTES // (1024 * 1024)} MB")

    safe_name = safe_filename(name)
    key = sha(bytes(data))
    for doc in project.get("documents", []):
        if doc.get("hash") == key:
            return False, f"Tài liệu trùng nội dung đã có: {doc.get('name')} ({doc.get('id')})"

    payload = document_payload(safe_name, bytes(data))
    extracted = payload["text"]
    if len(extracted.strip()) < MIN_TEXT_CHARS:
        raise ValueError("Không tìm thấy đủ văn bản trong tệp.")

    project.setdefault("documents", []).append(
        {
            "id": uid(),
            "name": safe_name,
            "hash": key,
            "text": extracted,
            "chars": len(extracted),
            "place_scope": str(place_scope or "").strip(),
            "source_label": str(source_label or "").strip(),
            "pages": payload["pages"],
            "warnings": payload["warnings"],
            "created_at": now_iso(),
        }
    )
    return True, f"Đã thêm {safe_name}: {len(extracted):,} ký tự."


def chunk_records(
    text: str,
    limit: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    doc_id: str = "",
    pages: list[dict] | None = None,
) -> list[dict]:
    if limit < 100:
        raise ValueError("Kích thước đoạn phải từ 100 ký tự")
    if overlap < 0 or overlap >= limit:
        raise ValueError("Độ chồng lấp phải nhỏ hơn kích thước đoạn")

    text = text or ""
    if not text.strip():
        return []

    output: list[dict] = []
    start = 0
    number = 0
    while start < len(text):
        end = min(len(text), start + limit)
        if end < len(text):
            window = start + int(limit * 0.6)
            candidates = [text.rfind(sep, window, end) for sep in _BOUNDARY_SEPARATORS]
            cut = max(candidates)
            if cut > start:
                end = cut + (2 if text.startswith("\n\n", cut) else 1)
        raw = text[start:end]
        if raw.strip():
            left = len(raw) - len(raw.lstrip())
            right = len(raw.rstrip())
            s2, e2 = start + left, start + right
            part = text[s2:e2]
            number += 1
            output.append(
                {
                    "doc_id": doc_id,
                    "chunk_number": number,
                    "text": part,
                    "start_char": s2,
                    "end_char": e2,
                    "chunk_hash": sha(part),
                    "page_from": page_at(pages, s2),
                    "page_to": page_at(pages, max(s2, e2 - 1)),
                }
            )
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return output


def document_chunks(document: dict, limit: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[dict]:
    return chunk_records(
        document.get("text", ""),
        limit,
        overlap,
        document.get("id", ""),
        document.get("pages"),
    )


def count_chunks(text: str, limit: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> int:
    """Đếm số đoạn nhanh bằng chỉ mục con trỏ, không cấp phát dictionary hay băm SHA cho từng chunk."""
    if limit < 100 or overlap < 0 or overlap >= limit:
        return 0
    text = text or ""
    n = len(text)
    if not text.strip():
        return 0

    count = 0
    start = 0
    while start < n:
        end = min(n, start + limit)
        if end < n:
            window = start + int(limit * 0.6)
            candidates = [text.rfind(sep, window, end) for sep in _BOUNDARY_SEPARATORS]
            cut = max(candidates)
            if cut > start:
                end = cut + (2 if text.startswith("\n\n", cut) else 1)
        # Kiểm tra nhanh có nội dung không rỗng
        if any(not text[idx].isspace() for idx in range(start, min(n, end))):
            count += 1
        if end >= n:
            break
        start = max(start + 1, end - overlap)
    return count

