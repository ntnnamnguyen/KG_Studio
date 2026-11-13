"""Package Thao tác Hàng loạt, Bản nháp Quyết định, Xem trước & Áp dụng Lô cho EDC."""
from __future__ import annotations

from .logic import build_preview_for_scope, execute_batch_apply, quick_apply_proposal_batch
from .view import render_edc_bulk_actions

__all__ = [
    "build_preview_for_scope",
    "execute_batch_apply",
    "quick_apply_proposal_batch",
    "render_edc_bulk_actions",
]
