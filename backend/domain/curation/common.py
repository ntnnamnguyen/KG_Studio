"""Các hàm tiện ích tra cứu thực thể, quan hệ và chuẩn hóa chuỗi cơ sở cho Curation."""
from __future__ import annotations

import re
import unicodedata

from shared.text_utils import normal, sha


def clean_display_text(value: str) -> str:
    """Chuẩn hóa NFC và gộp khoảng trắng nhưng giữ nguyên dấu tiếng Việt và chữ hoa/thường để hiển thị."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or "")).strip())


def clean_aliases(aliases: list[str] | str | None, primary_name: str = "") -> list[str]:
    """Chuẩn hóa danh sách bí danh: NFC, loại trùng theo normal() và loại bí danh trùng tên chính."""
    if aliases is None:
        return []
    raw_list = [x.strip() for x in aliases.split(";") if x.strip()] if isinstance(aliases, str) else list(aliases)
    primary_norm = normal(primary_name)
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_list:
        cleaned = clean_display_text(str(item))
        if not cleaned:
            continue
        norm_val = normal(cleaned)
        if not norm_val or norm_val == primary_norm or norm_val in seen:
            continue
        seen.add(norm_val)
        result.append(cleaned)
    return result


def doc_fingerprint(doc: dict | None) -> str:
    if not doc:
        return ""
    if doc.get("hash"):
        return str(doc["hash"])[:16]
    return sha(str(doc.get("text", "")))[:16]


def find_document(project: dict, doc_id: str) -> dict | None:
    return next((d for d in project.get("documents", []) if d.get("id") == doc_id), None)


def resolve_active_node_id(project: dict, node_id: str) -> str:
    """Phân giải node_id qua bảng ánh xạ node_redirects (chống vòng lặp)."""
    redirects = project.get("node_redirects") or {}
    current = str(node_id or "")
    visited: set[str] = set()
    while current in redirects and current not in visited:
        visited.add(current)
        current = str(redirects[current])
    return current


def find_node(project: dict, node_id: str) -> dict | None:
    return next((n for n in project.get("nodes", []) if n.get("id") == node_id), None)


def find_edge(project: dict, edge_id: str) -> dict | None:
    return next((e for e in project.get("edges", []) if e.get("id") == edge_id), None)

