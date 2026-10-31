"""Component cấu hình EDC+R (dùng ở Trang 2) và điểm nối tương thích cho Trang 4."""
from __future__ import annotations

from shared.constants import MODE_EDC, MODE_EDC_PLUS_R, MODE_FIXED

MODE_LABELS = {
    MODE_FIXED: "Danh mục cố định",
    MODE_EDC: "EDC mở — đề xuất định nghĩa (1 lượt)",
    MODE_EDC_PLUS_R: "EDC + R — Truy xuất quan hệ (+R) & Chuẩn hóa tự động (Target Alignment)",
}


def render_edc_mode_settings(project: dict) -> None:
    """Ủy quyền sang component quản lý phiên bản prompt và chế độ trích xuất chuẩn hóa."""
    from frontend.components.prompt_editor import render_prompt_management_panel
    render_prompt_management_panel(project)


def render_edc_alignment_curation(project: dict) -> None:
    """Điểm nối tương thích: uỷ quyền sang bố cục hai bảng độc lập của Trang 4."""
    from frontend.pages.p04_edc_alignment import render_edc_alignment_page

    render_edc_alignment_page(project)
