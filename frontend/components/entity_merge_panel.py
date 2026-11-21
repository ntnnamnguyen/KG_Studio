"""Khung phát hiện thực thể nghi trùng và bàn gộp 2..N thực thể theo quy trình 3 bước (Trang 5), kèm Gộp quan hệ tương đồng."""
from __future__ import annotations

import streamlit as st

from backend.domain.curation.service import node_degrees
from frontend.client import get_client
from frontend.components.merge import (
    render_entity_merge_history_body,
    render_entity_merge_tab,
    render_entity_type_merge_tab,
    render_relation_merge_tab,
    render_triple_dedup_history_body,
    render_triple_dedup_tab,
)
from frontend.components.merge.entity_tab import (
    build_entity_merge_preview,
    execute_entity_merge_apply,
)
from frontend.state.session import get_curation_section_state

# Backward compatibility aliases
_render_entity_merge_tab = render_entity_merge_tab
_render_relation_merge_tab = render_relation_merge_tab
_render_entity_type_merge_tab = render_entity_type_merge_tab
_render_triple_dedup_tab = render_triple_dedup_tab

__all__ = [
    "build_entity_merge_preview",
    "execute_entity_merge_apply",
    "render_entity_merge_history_body",
    "render_entity_merge_panel",
    "render_entity_merge_tab",
    "render_entity_type_merge_tab",
    "render_relation_merge_tab",
    "render_triple_dedup_history_body",
    "render_triple_dedup_tab",
]


def render_entity_merge_panel(project: dict, *, show_history: bool = True) -> None:
    """Hiển thị bàn phát hiện và gộp thực thể trùng lặp (Bước 2 trong quy trình kiểm duyệt 3 bước)."""
    client = get_client()
    m_state = get_curation_section_state(project, "merge")
    nodes = project.get("nodes", [])
    nodes_by_id = {str(n["id"]): n for n in nodes if n.get("id")}
    degrees = node_degrees(project)

    st.info(
        "💡 **Quy trình kiểm duyệt tinh gọn 3 bước:** Khu vực này tập trung 100% vào **Gộp Thực thể (Node) & Làm giàu Từ điển Bí danh**. "
        "Các công cụ chuẩn hóa nhãn quan hệ/loại thực thể đã được gom về **Bước 1 (Chuẩn hóa Lược đồ)**, "
        "và công cụ **Khử trùng Cạnh Lặp (Triple Deduplication)** được đặt tại **Bước 3 (Khử Cạnh Lặp & Duyệt Bằng chứng)**."
    )
    render_entity_merge_tab(project, client, m_state, nodes, nodes_by_id, degrees, show_history=show_history)
