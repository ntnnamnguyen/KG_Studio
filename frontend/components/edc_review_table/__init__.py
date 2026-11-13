"""Package Bảng Duyệt EDC độc lập cho từng nhóm (`entity_types` / `relations`)."""
from __future__ import annotations

from .drawer import render_proposal_detail_drawer
from .logic import (
    STATUS_LABELS_VN,
    build_table_display_rows,
    compute_filter_signature,
    filter_and_sort_proposals,
    paginate_proposals,
    status_label_vn,
    verification_badge_label,
)
from .table_view import render_edc_review_table

__all__ = [
    "STATUS_LABELS_VN",
    "build_table_display_rows",
    "compute_filter_signature",
    "filter_and_sort_proposals",
    "paginate_proposals",
    "render_edc_review_table",
    "render_proposal_detail_drawer",
    "status_label_vn",
    "verification_badge_label",
]
