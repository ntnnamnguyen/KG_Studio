"""Hằng số điều hướng, helper truy cập store và thao tác chọn ID dùng chung cho Session State."""
from __future__ import annotations

import copy
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
        state_dict["sel_editor_nonce"] = int(state_dict.get("sel_editor_nonce") or 0) + 1
        return list(state_dict["selected_ids"])
    if action == "select_all":
        state_dict["selected_ids"] = list(dict.fromkeys(eligible_ids or []))
        state_dict["sel_editor_nonce"] = int(state_dict.get("sel_editor_nonce") or 0) + 1
        return list(state_dict["selected_ids"])
    if action == "clear":
        state_dict["selected_ids"] = []
        state_dict["filter_prune_notice"] = ""
        state_dict["sel_editor_nonce"] = int(state_dict.get("sel_editor_nonce") or 0) + 1
        return None
    if action == "reconcile":
        prev_sig = state_dict.get("last_filter_sig", "")
        state_dict["last_filter_sig"] = filter_signature
        kept, pruned_count, notice = reconcile_id_selection(
            state_dict["selected_ids"], visible_eligible_ids or set(), prev_sig, filter_signature, item_noun=item_noun
        )
        state_dict["selected_ids"] = kept
        state_dict["filter_prune_notice"] = notice
        if pruned_count > 0:
            state_dict["sel_editor_nonce"] = int(state_dict.get("sel_editor_nonce") or 0) + 1
        return pruned_count


def _clone_if_mutable(value: Any) -> Any:
    return copy.deepcopy(value) if isinstance(value, (list, dict, set)) else value


def bump_sync_nonce(nonce_key: str, state_store: dict[str, Any] | None = None) -> int:
    """Tăng bộ đếm đồng bộ (nonce) để buộc widget có key cập nhật lại từ model state."""
    store = _store(state_store)
    next_val = int(store.get(nonce_key) or 0) + 1
    store[nonce_key] = next_val
    return next_val


def sync_keyed_value(
    widget_key: str,
    desired_value: Any,
    sync_tag: Any,
    *,
    tag_key: str | None = None,
    state_store: dict[str, Any] | None = None,
) -> Any:
    """Đồng bộ pre-render cho widget dùng `key=` mà không truyền `value=`/`default=`."""
    store = _store(state_store)
    marker_key = tag_key or f"_wsync::{widget_key}"
    if widget_key not in store or store.get(marker_key) != sync_tag:
        store[widget_key] = _clone_if_mutable(desired_value)
        store[marker_key] = sync_tag
    return store[widget_key]


def sync_keyed_choice(
    widget_key: str,
    valid_options: list[Any] | tuple[Any, ...],
    desired_value: Any,
    sync_tag: Any,
    *,
    tag_key: str | None = None,
    state_store: dict[str, Any] | None = None,
) -> Any:
    """Đồng bộ pre-render cho selectbox/radio dùng `key=` (không truyền `index=`), tự sửa nếu option cũ không còn hợp lệ."""
    store = _store(state_store)
    opts = list(valid_options)
    marker_key = tag_key or f"_wsync::{widget_key}"
    if not opts:
        if widget_key not in store or store.get(marker_key) != sync_tag:
            store[widget_key] = desired_value
            store[marker_key] = sync_tag
        return store[widget_key]

    target = desired_value if desired_value in opts else opts[0]
    if (
        widget_key not in store
        or store.get(marker_key) != sync_tag
        or store.get(widget_key) not in opts
    ):
        store[widget_key] = target
        store[marker_key] = sync_tag
    return store[widget_key]


def sync_keyed_multiselect(
    widget_key: str,
    valid_options: list[Any] | tuple[Any, ...],
    desired_values: list[Any] | tuple[Any, ...],
    sync_tag: Any,
    *,
    tag_key: str | None = None,
    state_store: dict[str, Any] | None = None,
) -> list[Any]:
    """Đồng bộ pre-render cho multiselect dùng `key=` (không truyền `default=`), lọc bỏ option hết hiệu lực."""
    store = _store(state_store)
    opts = list(valid_options)
    valid_set = set(opts)
    marker_key = tag_key or f"_wsync::{widget_key}"
    if widget_key not in store or store.get(marker_key) != sync_tag or not isinstance(store.get(widget_key), list):
        store[widget_key] = [v for v in desired_values if v in valid_set]
        store[marker_key] = sync_tag
    else:
        filtered = [v for v in store[widget_key] if v in valid_set]
        if len(filtered) != len(store[widget_key]):
            store[widget_key] = filtered
    return list(store[widget_key])


def sync_keyed_int(
    widget_key: str,
    desired_value: int,
    sync_tag: Any,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
    tag_key: str | None = None,
    state_store: dict[str, Any] | None = None,
) -> int:
    """Đồng bộ pre-render cho number_input/slider số nguyên dùng `key=` và luôn kẹp trong `[min_value, max_value]`."""
    def _clamp(val: Any) -> int:
        try:
            iv = int(val)
        except (TypeError, ValueError):
            iv = int(min_value if min_value is not None else 0)
        if max_value is not None and iv > max_value:
            iv = max_value
        if min_value is not None and iv < min_value:
            iv = min_value
        return iv

    store = _store(state_store)
    marker_key = tag_key or f"_wsync::{widget_key}"
    if widget_key not in store or store.get(marker_key) != sync_tag:
        store[widget_key] = _clamp(desired_value)
        store[marker_key] = sync_tag
    else:
        clamped = _clamp(store.get(widget_key))
        if clamped != store.get(widget_key):
            store[widget_key] = clamped
    return int(store[widget_key])


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
    bump_sync_nonce("_nav_sync_nonce", state_store=store)
    return target_page


def get_active_step(state_store: dict[str, Any] | None = None) -> tuple[str, int, str]:
    """Trả về (step_id, step_index, page_label) của bước đang hoạt động."""
    store = _store(state_store)
    current_label = normalize_page_label(store.get("active_page", PAGE_LABELS[0]))
    idx = PAGE_LABELS.index(current_label) if current_label in PAGE_LABELS else 0
    step_id = PIPELINE_STEPS[idx]
    return step_id, idx, current_label
