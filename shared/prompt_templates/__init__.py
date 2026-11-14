"""Các mẫu câu lệnh (Instruct Templates) dùng chung cho Embedding và LLM trong EDC+R & ML Lab."""
from __future__ import annotations

from collections.abc import Sequence

PASSAGE_TEMPLATE_VERSION = "v2-domain-range"

SR_QUERY_INSTRUCT = (
    "Instruct: Truy xuất các mối quan hệ và định nghĩa thực thể phù hợp có mặt trong đoạn văn tiếng Việt sau.\n"
    "Query: {text}"
)

CANON_QUERY_INSTRUCT = (
    "Instruct: Cho một mối quan hệ hoặc loại thực thể cùng định nghĩa ngữ cảnh tiếng Việt, "
    "hãy truy xuất mục chuẩn tương đương nhất trong danh mục đích.\n"
    "Query: {name}: {definition}"
)


def should_use_e5_instruct(model_id: str | None) -> bool:
    """Chỉ dùng tiền tố E5 Instruct:/Query: cho model E5 hoặc hybrid_vn (vốn tự tách nhãn)."""
    m = (model_id or "").strip().lower()
    if not m or m.startswith("hybrid_vn:") or m.startswith("registry:"):
        return True
    return "e5" in m


def format_sr_query(chunk_text: str, *, use_instruct: bool = True) -> str:
    clean_text = (chunk_text or "").strip()
    if not use_instruct:
        return clean_text
    return SR_QUERY_INSTRUCT.format(text=clean_text)


def format_canon_query(name: str, definition: str, *, use_instruct: bool = True) -> str:
    clean_name = (name or "").strip()
    clean_def = (definition or "").strip()
    if not use_instruct:
        return f"{clean_name}: {clean_def}" if clean_def else clean_name
    return CANON_QUERY_INSTRUCT.format(name=clean_name, definition=clean_def)


def format_catalog_passage(
    name: str,
    definition: str = "",
    description: str = "",
    aliases: Sequence[str] | None = None,
    domain: str = "",
    range: str = "",
) -> str:
    name_clean = (name or "").strip()
    def_clean = (definition or "").strip()
    desc_clean = (description or "").strip()
    dom_clean = (domain or "").strip()
    rng_clean = (range or "").strip()
    alias_str = ", ".join(str(a).strip() for a in (aliases or []) if str(a).strip())
    parts = [p for p in (def_clean, desc_clean) if p]
    if dom_clean or rng_clean:
        parts.append(f"Scope: {dom_clean or '*'} -> {rng_clean or '*'}")
    if alias_str:
        parts.append(f"Aliases: {alias_str}")
    body = " | ".join(parts)
    return f"{name_clean}: {body}" if body else name_clean

