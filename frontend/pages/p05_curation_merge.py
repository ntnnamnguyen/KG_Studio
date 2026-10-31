"""Màn hình 05: Kiểm duyệt Quan hệ, Quản lý Hồ sơ Thực thể & Gộp Thực thể (Tích hợp trong Knowledge Curation Hub)."""
from __future__ import annotations

from frontend.pages.p04_curation_hub import (
    compute_curation_overview_counts,
    render_curation_hub_page,
)


def render_curation_merge_page(project: dict) -> None:
    """Điều hướng hiển thị Phân khu Kiểm duyệt Đồ thị (Quan hệ / Thực thể) trong Hub Kiểm duyệt."""
    render_curation_hub_page(project, default_tab="edges")

