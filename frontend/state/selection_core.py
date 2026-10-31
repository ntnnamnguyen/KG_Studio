"""Thao tác danh sách ID thuần cho việc lựa chọn dòng trên giao diện (giữ nguyên thứ tự)."""
from __future__ import annotations

from typing import Iterable


def toggle_id_in_list(
    current_ids: list[str],
    item_id: str,
    selected: bool,
    is_eligible: bool = True,
) -> list[str]:
    """Thêm duy nhất (nếu đủ điều kiện) hoặc loại bỏ item_id khỏi danh sách hiện tại."""
    clean_id = str(item_id or "").strip()
    if not clean_id:
        return list(current_ids)
    if selected:
        if is_eligible and clean_id not in current_ids:
            current_ids.append(clean_id)
    else:
        if clean_id in current_ids:
            current_ids[:] = [x for x in current_ids if x != clean_id]
    return list(current_ids)


def append_unique_ids(
    current_ids: list[str],
    new_ids: Iterable[str],
) -> list[str]:
    """Bổ sung danh sách ID mới vào danh sách hiện tại theo thứ tự xuất hiện, bỏ qua trùng lặp."""
    for item_id in new_ids:
        clean_id = str(item_id or "").strip()
        if clean_id and clean_id not in current_ids:
            current_ids.append(clean_id)
    return list(current_ids)


def reconcile_id_selection(
    current_ids: list[str],
    visible_eligible_ids: set[str],
    prev_sig: str,
    new_sig: str,
    item_noun: str = "mục",
) -> tuple[list[str], int, str]:
    """
    Đối chiếu danh sách ID đã chọn với tập ID hợp lệ trong bộ lọc.
    Trả về: (danh sách ID được giữ lại, số lượng bị loại bỏ, chuỗi thông báo nếu có thay đổi filter).
    """
    if not prev_sig or prev_sig == new_sig:
        kept = [item_id for item_id in current_ids if item_id in visible_eligible_ids]
        return kept, 0, ""

    before_count = len(current_ids)
    kept = [item_id for item_id in current_ids if item_id in visible_eligible_ids]
    pruned_count = before_count - len(kept)
    notice = (
        f"Đã bỏ chọn {pruned_count} {item_noun} không còn nằm trong kết quả của bộ lọc mới."
        if pruned_count > 0
        else ""
    )
    return kept, pruned_count, notice
