"""Định dạng HTML hiển thị câu trích dẫn bằng chứng nổi bật trong ngữ cảnh văn bản gốc."""
from __future__ import annotations

import html
from typing import Any


def format_highlighted_evidence_html(ev_ctx: dict[str, Any]) -> str:
    """Tạo đoạn HTML an toàn (escape đầy đủ ký tự đặc biệt) đánh dấu nổi bật câu bằng chứng trong đoạn văn nguồn."""
    if not ev_ctx.get("found"):
        reason = html.escape(str(ev_ctx.get("reason") or "Không tìm thấy câu trích dẫn nguyên văn trong tài liệu."))
        return f"<div style='padding:10px;border-left:4px solid #d97706;background:#fffbeb;color:#92400e;'>{reason}</div>"

    before = html.escape(str(ev_ctx.get("before_text") or ""))
    quote = html.escape(str(ev_ctx.get("quote") or ""))
    after = html.escape(str(ev_ctx.get("after_text") or ""))
    return (
        "<div style='padding:12px;border:1px solid #cbd5e1;border-radius:6px;background:#f8fafc;"
        "line-height:1.65;white-space:pre-wrap;font-size:0.95rem;'>"
        f"{before}"
        f"<mark style='background:#fde047;padding:2px 4px;border-radius:3px;font-weight:600;'>{quote}</mark>"
        f"{after}"
        "</div>"
    )
