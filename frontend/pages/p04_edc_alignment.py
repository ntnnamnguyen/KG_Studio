"""Màn hình 04: Duyệt đề xuất EDC & Target Alignment (Tích hợp trong Knowledge Curation Hub)."""
from __future__ import annotations

from frontend.pages.p04_curation_hub import (
    compute_edc_overview_counts,
    render_curation_hub_page,
)


def render_edc_alignment_page(project: dict) -> None:
    """Điều hướng hiển thị Phân khu Lược đồ (Schema EDC) trong Hub Kiểm duyệt."""
    render_curation_hub_page(project, default_tab="schema")

