"""Các thành phần giao diện và tiện ích dùng chung cho Kiểm duyệt & Chuẩn hóa Tri thức (Trang 4 & 5)."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from frontend.client import get_client
from shared.text_utils import normal, sha


def render_sqlite_resync_banner(project: dict, key_prefix: str = "shared") -> None:
    """Hiển thị cảnh báo và nút bấm đồng bộ lại SQLite khi dự án có cờ sync_pending."""
    if not project.get("sync_pending"):
        return

    client = get_client()
    st.warning(
        f"⚠️ Dự án đang có trạng thái chờ đồng bộ SQLite (`{project.get('sync_error', '')}`). "
        "Bản JSON gốc đã được lưu an toàn trên ổ đĩa."
    )
    if st.button("🔄 Đồng bộ lại SQLite ngay", key=f"btn_{key_prefix}_resync_sqlite"):
        try:
            client.resync_sqlite(project)
            st.success("Đã đồng bộ lại SQLite thành công.")
            st.rerun()
        except Exception as exc:
            st.error(f"Lỗi đồng bộ SQLite: {exc}")


def paginate_items(
    items: list[Any],
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Any], int, int]:
    """Phân trang danh sách dữ liệu dùng chung; trả về (page_items, current_page, total_pages)."""
    size = max(1, int(page_size or 50))
    total_pages = max(1, math.ceil(len(items) / size))
    cur_page = max(1, min(int(page or 1), total_pages))
    start = (cur_page - 1) * size
    end = start + size
    return items[start:end], cur_page, total_pages


def compute_filter_hash(payload: dict[str, Any]) -> str:
    """Tính chữ ký xác định (hash) của bộ lọc để nhận diện sự thay đổi tiêu chí tìm kiếm/lọc."""
    normalized_payload = {
        k: (normal(str(v)) if isinstance(v, str) else v)
        for k, v in payload.items()
    }
    return sha(json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True))[:16]


def render_pagination_controls(
    current_page: int,
    total_pages: int,
    page_size: int = 50,
    page_size_options: list[int] = [10, 25, 50, 100],
    key_prefix: str = "shared",
) -> tuple[int, int]:
    """Thành phần phân trang dùng chung cho các bảng kiểm duyệt."""
    col_size, col_page = st.columns([1, 1.2])
    new_size = col_size.selectbox(
        "Số dòng/trang",
        page_size_options,
        index=page_size_options.index(page_size) if page_size in page_size_options else 1,
        key=f"{key_prefix}_page_size",
    )
    new_page = col_page.number_input(
        f"Trang (1..{total_pages})",
        min_value=1,
        max_value=max(1, total_pages),
        value=max(1, min(current_page, max(1, total_pages))),
        step=1,
        key=f"{key_prefix}_page_num",
    )
    return int(new_page), int(new_size)


def render_selection_action_bar(
    *,
    selected_count: int,
    page_eligible_count: int,
    filtered_eligible_count: int,
    total_count: int,
    key_prefix: str,
    item_noun: str = "mục",
    on_select_page: Callable[[], None] | None = None,
    on_select_all_filtered: Callable[[], None] | None = None,
    on_clear: Callable[[], None] | None = None,
    page_size: int | None = None,
    current_page: int | None = None,
    total_pages: int | None = None,
    page_size_options: list[int] = [10, 25, 50, 100],
    summary_text: str = "",
) -> tuple[int, int] | int | None:
    """Thanh công cụ thao tác chọn theo lô và tích hợp điều khiển phân trang dùng chung."""
    has_full_pagination = page_size is not None and current_page is not None and total_pages is not None
    has_page_only = page_size is None and current_page is not None and total_pages is not None

    if has_full_pagination:
        c1, c2, c3, c4, c5 = st.columns([1.2, 1.4, 1.0, 1.1, 1.3])
    elif has_page_only:
        c1, c2, c3, c4, c5 = st.columns([1.2, 1.5, 1.0, 1.2, 2.2])
    else:
        c1, c2, c3 = st.columns([1.2, 1.4, 1.0])

    if c1.button(
        f"☑️ Chọn trang này ({page_eligible_count})",
        disabled=(page_eligible_count == 0),
        width="stretch",
        key=f"{key_prefix}_btn_sel_page",
    ):
        if on_select_page:
            on_select_page()
            st.rerun()

    if c2.button(
        f"📑 Chọn tất cả lọc ({filtered_eligible_count})",
        disabled=(filtered_eligible_count == 0),
        width="stretch",
        key=f"{key_prefix}_btn_sel_all",
    ):
        if on_select_all_filtered:
            on_select_all_filtered()
            st.rerun()

    if c3.button(
        "✖️ Bỏ chọn" if has_page_only else "✖️ Bỏ chọn tất cả",
        disabled=(selected_count == 0),
        width="stretch",
        key=f"{key_prefix}_btn_clear_sel",
    ):
        if on_clear:
            on_clear()
            st.rerun()

    if has_full_pagination:
        new_size = c4.selectbox(
            "Số dòng/trang",
            page_size_options,
            index=page_size_options.index(page_size) if page_size in page_size_options else 1,
            key=f"{key_prefix}_page_size",
        )
        new_page = c5.number_input(
            f"Trang (1..{total_pages})",
            min_value=1,
            max_value=max(1, total_pages),
            value=max(1, min(current_page, max(1, total_pages))),
            step=1,
            key=f"{key_prefix}_page_num",
        )
        return int(new_page), int(new_size)

    if has_page_only:
        new_page = current_page
        if total_pages > 1:
            new_page = c4.number_input(
                f"Trang (1..{total_pages})",
                min_value=1,
                max_value=max(1, total_pages),
                value=max(1, min(current_page, max(1, total_pages))),
                step=1,
                key=f"{key_prefix}_page_num",
            )
        else:
            c4.write("")

        text = summary_text or (
            f"**Đã chọn `{selected_count}`** / `{filtered_eligible_count}` kết quả lọc / `{total_count}` tổng số {item_noun}"
        )
        c5.markdown(text)
        return int(new_page)

    return None


def render_decision_batch_history(
    project: dict,
    batch_key: str,
    title: str,
    *,
    on_restore_callbacks: list[Callable] | None = None,
    key_prefix: str = "batch",
    enable_jump_to_proposal: bool = False,
) -> None:
    """Hiển thị lịch sử các lô quyết định đã thực thi và hỗ trợ khôi phục Snapshot toàn vẹn."""
    client = get_client()
    batches = list(reversed(project.get(batch_key, [])))

    with st.expander(f"📜 {title} ({len(batches)} lô đã lưu)", expanded=False):
        if not batches:
            st.info("Dự án chưa có lô quyết định nào được lưu.")
            return

        batch_options = [b.get("batch_id", "") for b in batches if b.get("batch_id")]
        by_batch_id = {b["batch_id"]: b for b in batches if b.get("batch_id")}

        def _format_batch(bid: str) -> str:
            b = by_batch_id.get(bid, {})
            op = b.get("operation") or (
                "Loại thực thể" if b.get("kind") == "entity_types" else ("Quan hệ" if b.get("kind") == "relations" else "Lô quyết định")
            )
            applied_count = len(b.get("applied_ids", []))
            at_time = b.get("at", "")
            return f"Lô {bid} · {op} · Đã áp dụng: {applied_count} mục · Lúc: {at_time}"

        chosen_batch_id = st.selectbox(
            "Chọn lô quyết định để xem chi tiết:",
            batch_options,
            format_func=_format_batch,
            key=f"{key_prefix}_select_batch",
        )
        batch = by_batch_id.get(chosen_batch_id, {})
        counts = batch.get("counts", {})
        if counts:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Duyệt mới (approved)", counts.get("approved", 0))
            c2.metric("Hợp nhất (merged)", counts.get("merged", 0))
            c3.metric("Từ chối (rejected)", counts.get("rejected", 0))
            c4.metric("Chưa xử lý / Giữ lại", counts.get("unprocessed", 0))

        st.caption(
            f"Mã request: `{batch.get('request_id', '')}` · Chế độ: `{batch.get('apply_mode', '')}` · "
            f"Revision: `{batch.get('revision_before', '')}` → `{batch.get('revision_after', '')}` · "
            f"Snapshot: `{batch.get('snapshot_path', '') or 'Không có'}`"
        )

        item_results = batch.get("item_results", [])
        if item_results:
            st.dataframe(item_results, width='stretch', hide_index=True)

            if enable_jump_to_proposal:
                from frontend.state.session import set_focused_proposal
                jump_ids = [r.get("proposal_id", "") for r in item_results if r.get("proposal_id")]
                if jump_ids:
                    j_col1, j_col2 = st.columns([2.0, 1.0])
                    jump_pid = j_col1.selectbox(
                        "Đi tới xem chi tiết đề xuất trong lô này:",
                        jump_ids,
                        key=f"{key_prefix}_jump_prop_{chosen_batch_id}",
                    )
                    if j_col2.button("🔎 Mở chi tiết đề xuất", key=f"{key_prefix}_btn_jump_{chosen_batch_id}"):
                        set_focused_proposal(project, str(batch.get("kind", "entity_types")), jump_pid)
                        st.rerun()

        snap_str = str(batch.get("snapshot_path") or "")
        if snap_str and Path(snap_str).exists():
            st.warning(
                "⚠️ **Lưu ý khôi phục Snapshot:** Khôi phục snapshot sẽ đưa **toàn bộ dự án** "
                "(tài liệu, danh mục, đề xuất, node, cạnh) về thời điểm ngay trước khi lô này được áp dụng, "
                "đồng thời đồng bộ lại SQLite và chỉ mục vector."
            )
            confirm_restore = st.checkbox(
                f"Tôi hiểu phạm vi ảnh hưởng và xác nhận khôi phục toàn dự án về snapshot trước lô `{chosen_batch_id}`",
                key=f"{key_prefix}_chk_restore_{chosen_batch_id}",
            )
            if st.button(
                "⏪ Khôi phục toàn dự án về Snapshot trước lô này",
                disabled=not confirm_restore,
                key=f"{key_prefix}_btn_restore_{chosen_batch_id}",
            ):
                client.restore_snapshot(project, snap_str)
                if on_restore_callbacks:
                    for cb in on_restore_callbacks:
                        cb(project)
                st.success(f"Đã khôi phục dự án về snapshot `{Path(snap_str).name}`.")
                st.rerun()

