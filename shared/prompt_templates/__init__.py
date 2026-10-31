"""Các mẫu câu lệnh (Instruct Templates) dùng chung cho Embedding và LLM trong EDC+R & ML Lab."""
from __future__ import annotations

SR_QUERY_INSTRUCT = (
    "Instruct: Truy xuất các mối quan hệ và định nghĩa thực thể phù hợp có mặt trong đoạn văn tiếng Việt sau.\n"
    "Query: {text}"
)

CANON_QUERY_INSTRUCT = (
    "Instruct: Cho một mối quan hệ hoặc loại thực thể cùng định nghĩa ngữ cảnh tiếng Việt, "
    "hãy truy xuất mục chuẩn tương đương nhất trong danh mục đích.\n"
    "Query: {name}: {definition}"
)


def format_sr_query(chunk_text: str) -> str:
    return SR_QUERY_INSTRUCT.format(text=(chunk_text or "").strip())


def format_canon_query(name: str, definition: str) -> str:
    return CANON_QUERY_INSTRUCT.format(name=(name or "").strip(), definition=(definition or "").strip())


def format_catalog_passage(name: str, definition: str = "", description: str = "") -> str:
    name_clean = (name or "").strip()
    def_clean = (definition or "").strip()
    desc_clean = (description or "").strip()
    body = " | ".join(part for part in (def_clean, desc_clean) if part)
    return f"{name_clean}: {body}" if body else name_clean

