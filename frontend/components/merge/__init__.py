"""Các tab chức năng gộp và chuẩn hóa đồ thị (Merge & Curation Sub-tabs)."""
from __future__ import annotations

from .entity_tab import render_entity_merge_tab
from .entity_type_tab import render_entity_type_merge_tab
from .relation_tab import render_relation_merge_tab
from .triple_dedup_tab import render_triple_dedup_tab

__all__ = [
    "render_entity_merge_tab",
    "render_entity_type_merge_tab",
    "render_relation_merge_tab",
    "render_triple_dedup_tab",
]
