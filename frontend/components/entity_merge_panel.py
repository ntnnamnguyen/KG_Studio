"""Khung phát hiện thực thể nghi trùng và bàn gộp 2..N thực thể theo quy trình 3 bước (Trang 5), kèm Gộp quan hệ tương đồng."""
from __future__ import annotations

import streamlit as st

from backend.domain.curation.service import node_degrees
from frontend.client import get_client
from frontend.components.merge import (
    render_entity_merge_tab,
    render_entity_type_merge_tab,
    render_relation_merge_tab,
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
    "render_entity_merge_panel",
    "render_entity_merge_tab",
    "render_entity_type_merge_tab",
    "render_relation_merge_tab",
    "render_triple_dedup_tab",
]


def render_entity_merge_panel(project: dict) -> None:
    """Hiển thị Phân khu 3: Quản lý & Gộp thực thể, Gộp quan hệ, Chuẩn hóa loại thực thể và Khử trùng cạnh lặp."""
    client = get_client()
    m_state = get_curation_section_state(project, "merge")
    nodes = project.get("nodes", [])
    nodes_by_id = {str(n["id"]): n for n in nodes if n.get("id")}
    degrees = node_degrees(project)

    tab_ent, tab_rel, tab_types, tab_dedup = st.tabs([
        "🏛️ 1. Gộp Thực thể (Entity Merge)",
        "🔗 2. Gộp Quan hệ (Relation Merge)",
        "🏷️ 3. Chuẩn hóa Loại Thực thể (Entity Type Merge)",
        "✨ 4. Khử trùng Cạnh Lặp (Triple Deduplication)",
    ])

    with tab_ent:
        render_entity_merge_tab(project, client, m_state, nodes, nodes_by_id, degrees)

    with tab_rel:
        render_relation_merge_tab(project, client, m_state)

    with tab_types:
        render_entity_type_merge_tab(project, client, m_state)

    with tab_dedup:
        render_triple_dedup_tab(project, client)
