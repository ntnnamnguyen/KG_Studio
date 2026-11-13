"""Hằng số điều hướng, helper truy cập store và thao tác chọn ID dùng chung cho Session State."""
from __future__ import annotations

from typing import Any

import streamlit as st

from .selection_core import append_unique_ids, reconcile_id_selection, toggle_id_in_list

PIPELINE_STEPS: list[str] = [
    "documents",    # Bước 1: Tài liệu
    "setup",        # Bước 2: Thiết lập
    "extraction",   # Bước 3: Trích xuất
    "review",       # Bước 4: Rà soát
    "explore",      # Bước 5: Khai thác
]

PAGE_LABELS: list[str] = [
    "1. Tài liệu",
    "2. Thiết lập",
    "3. Trích xuất",
    "4. Rà soát",
    "5. Khai thác",
]

# Ánh xạ tương thích ngược cho các nhãn phiên cũ và step IDs
LEGACY_PAGE_LABEL_MAP: dict[str, str] = {
    "1. Dự án & Tài liệu": "1. Tài liệu",
    "2. Danh mục, EDC+R & ML Lab": "2. Thiết lập",
    "3. Trích xuất & Trace": "3. Trích xuất",
    "4. Kiểm duyệt & Chuẩn hóa Tri thức": "4. Rà soát",
    "5. Đồ thị & Xuất Neo4j": "5. Khai thác",
    "documents": "1. Tài liệu",
    "setup": "2. Thiết lập",
    "extraction": "3. Trích xuất",
    "review": "4. Rà soát",
    "explore": "5. Khai thác",
    "1. Tài liệu": "1. Tài liệu",
    "2. Thiết lập": "2. Thiết lập",
    "3. Trích xuất": "3. Trích xuất",
    "4. Rà soát": "4. Rà soát",
    "5. Khai thác": "5. Khai thác",
}

STEP_INDEX_MAP: dict[str, int] = {
    "documents": 0,
    "setup": 1,
    "extraction": 2,
    "review": 3,
    "explore": 4,
}


def _store(state_store: dict[str, Any] | None = None) -> Any:
    return state_store if state_store is not None else st.session_state


def _apply_selection_state(
    state_dict: dict[str, Any],
    action: str,
    *,
    item_id: str = "",
    selected: bool = False,
    is_eligible: bool = True,
    eligible_ids: list[str] | None = None,
    visible_eligible_ids: set[str] | None = None,
    filter_signature: str = "",
    item_noun: str = "mục",
) -> Any:
    """Helper cấp phát thực thi các thao tác danh sách ID lựa chọn dùng chung."""
    if action == "toggle":
        state_dict["selected_ids"] = toggle_id_in_list(state_dict["selected_ids"], item_id, selected, is_eligible)
        return list(state_dict["selected_ids"])
    if action == "select_page":
        state_dict["selected_ids"] = append_unique_ids(state_dict["selected_ids"], eligible_ids or [])
        return list(state_dict["selected_ids"])
    if action == "select_all":
        state_dict["selected_ids"] = list(dict.fromkeys(eligible_ids or []))
        return list(state_dict["selected_ids"])
    if action == "clear":
        state_dict["selected_ids"] = []
        state_dict["filter_prune_notice"] = ""
        return None
    if action == "reconcile":
        prev_sig = state_dict.get("last_filter_sig", "")
        state_dict["last_filter_sig"] = filter_signature
        kept, pruned_count, notice = reconcile_id_selection(
            state_dict["selected_ids"], visible_eligible_ids or set(), prev_sig, filter_signature, item_noun=item_noun
        )
        state_dict["selected_ids"] = kept
        state_dict["filter_prune_notice"] = notice
        return pruned_count


def normalize_page_label(label: str) -> str:
    """Chuẩn hóa nhãn trang (hỗ trợ cả nhãn cũ và step id)."""
    return LEGACY_PAGE_LABEL_MAP.get(str(label), label if label in PAGE_LABELS else PAGE_LABELS[0])


def navigate_to_step(step_name_or_index: str | int, state_store: dict[str, Any] | None = None) -> str:
    """Điều hướng sang một bước trong pipeline theo ID ('documents', 'setup', v.v.) hoặc index (0..4)."""
    store = _store(state_store)
    if isinstance(step_name_or_index, int):
        idx = max(0, min(step_name_or_index, len(PAGE_LABELS) - 1))
        target_page = PAGE_LABELS[idx]
        target_step = PIPELINE_STEPS[idx]
    else:
        norm = normalize_page_label(str(step_name_or_index))
        target_page = norm
        idx = PAGE_LABELS.index(target_page) if target_page in PAGE_LABELS else 0
        target_step = PIPELINE_STEPS[idx]
    store["active_page"] = target_page
    store["active_step"] = target_step
    return target_page


def get_active_step(state_store: dict[str, Any] | None = None) -> tuple[str, int, str]:
    """Trả về (step_id, step_index, page_label) của bước đang hoạt động."""
    store = _store(state_store)
    current_label = normalize_page_label(store.get("active_page", PAGE_LABELS[0]))
    idx = PAGE_LABELS.index(current_label) if current_label in PAGE_LABELS else 0
    step_id = PIPELINE_STEPS[idx]
    return step_id, idx, current_label
