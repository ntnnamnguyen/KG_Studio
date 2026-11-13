"""Package khung đối chiếu dữ kiện & bằng chứng hai cột và hồ sơ thực thể (Trang 4)."""
from __future__ import annotations

from .edge_inspector import render_edge_evidence_and_inspector_panel
from .entity_inspector import render_entity_profile_inspector
from .html_format import format_highlighted_evidence_html

__all__ = [
    "format_highlighted_evidence_html",
    "render_edge_evidence_and_inspector_panel",
    "render_entity_profile_inspector",
]
