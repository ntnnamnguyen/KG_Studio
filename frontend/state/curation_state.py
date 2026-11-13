"""Quản lý trạng thái Trang 4: Kiểm duyệt quan hệ, Thực thể & Gộp thực thể (edges / entities / merge)."""
from __future__ import annotations

import copy
from typing import Any

from shared.constants import STATUS_CHECK, STATUS_PENDING
from shared.schemas.curation import (
    CurationPreviewDTO,
    CurationResultDTO,
    EdgeReviewDecisionDTO,
    EntityMergePreviewDTO,
)
from shared.text_utils import uid
from .core import _apply_selection_state, _store


def _default_curation_section_state(project_id: str, section: str) -> dict[str, Any]:
    if section == "edges":
        return {
            "project_id": project_id,
            "section": "edges",
            "selected_ids": [],
            "focused_edge_id": "",
            "drafts": {},
            "active_preview": None,
            "preview_decisions": [],
            "preview_request_id": "",
            "last_result": None,
            "filter_prune_notice": "",
            "last_filter_sig": "",
            "filters": {
                "status": "all",
                "doc_id": "all",
                "relation": "all",
                "entity_id": "all",
                "entity_kind": "all",
                "evidence_state": "all",
                "schema_state": "all",
                "search": "",
                "sort_by": "priority",
                "sort_desc": False,
                "page_size": 25,
                "page": 1,
            },
        }
    if section == "entities":
        return {
            "project_id": project_id,
            "section": "entities",
            "selected_ids": [],
            "focused_node_id": "",
            "drafts": {},
            "last_result": None,
            "filter_prune_notice": "",
            "last_filter_sig": "",
            "filters": {
                "kind": "all",
                "doc_id": "all",
                "schema_state": "all",
                "degree_filter": "all",
                "dup_candidate_only": False,
                "search": "",
                "sort_by": "degree_desc",
                "page_size": 25,
                "page": 1,
            },
        }
    if section == "merge":
        return {
            "project_id": project_id,
            "section": "merge",
            "member_ids": [],
            "keep_id": "",
            "canonical_name": "",
            "canonical_kind": "",
            "kind_resolution_note": "",
            "canonical_description": "",
            "alias_overrides": None,
            "note": "",
            "fuzzy_threshold": 0.82,
            "active_preview": None,
            "preview_request_id": "",
            "last_result": None,
        }
    raise ValueError(f"Phân khu Trang 5 không hợp lệ: {section}")


def reset_curation_state_if_project_changed(project: dict, state_store: dict[str, Any] | None = None) -> bool:
    """Khi đổi dự án: đặt lại toàn bộ lựa chọn, bộ lọc, bản nháp và xem trước của Trang 5."""
    store = _store(state_store)
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    prev_id = store.get("_curation_active_project_id")
    changed = prev_id != proj_id
    if changed or not isinstance(store.get("_curation_sections"), dict):
        store["_curation_active_project_id"] = proj_id
        store["_curation_active_section"] = "edges"
        store["_curation_return_context"] = None
        store["_curation_sections"] = {
            "edges": _default_curation_section_state(proj_id, "edges"),
            "entities": _default_curation_section_state(proj_id, "entities"),
            "merge": _default_curation_section_state(proj_id, "merge"),
        }
    return changed


def get_curation_section_state(
    project: dict,
    section: str,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lấy (hoặc khởi tạo nếu thiếu) dictionary trạng thái cho phân khu `edges` / `entities` / `merge`."""
    if section not in ("edges", "entities", "merge"):
        raise ValueError(f"Phân khu Trang 5 không hợp lệ: {section}")
    store = _store(state_store)
    reset_curation_state_if_project_changed(project, store)
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    sections = store.setdefault("_curation_sections", {})
    if section not in sections or sections[section].get("project_id") != proj_id:
        sections[section] = _default_curation_section_state(proj_id, section)
    return sections[section]


def get_active_curation_section(project: dict, state_store: dict[str, Any] | None = None) -> str:
    """Trả về tên phân khu đang hoạt động trong Trang Rà soát."""
    store = _store(state_store)
    reset_curation_state_if_project_changed(project, store)
    sec = str(store.get("_curation_active_section") or "edges")
    return sec if sec in ("edges", "entities", "merge") else "edges"


def set_active_curation_section(
    project: dict,
    section: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Chuyển phân khu đang hoạt động trong Trang Rà soát."""
    if section not in ("edges", "entities", "merge"):
        raise ValueError(f"Phân khu Trang 5 không hợp lệ: {section}")
    store = _store(state_store)
    reset_curation_state_if_project_changed(project, store)
    store["_curation_active_section"] = section


def invalidate_curation_preview(
    project: dict,
    section: str = "edges",
    state_store: dict[str, Any] | None = None,
) -> None:
    """Làm mất hiệu lực bản xem trước khi dữ liệu nháp thay đổi."""
    s_state = get_curation_section_state(project, section, state_store)
    s_state["active_preview"] = None
    if section == "edges":
        s_state["preview_decisions"] = []
    s_state["preview_request_id"] = ""


def set_focused_edge(
    project: dict,
    edge_id: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Mở xem chi tiết một cạnh mà KHÔNG tự đánh dấu chọn hoặc duyệt cạnh đó."""
    s_state = get_curation_section_state(project, "edges", state_store)
    s_state["focused_edge_id"] = str(edge_id or "").strip()


def set_focused_entity(
    project: dict,
    node_id: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Mở hồ sơ một thực thể để xem/sửa mà KHÔNG tự gộp hay chọn hàng loạt."""
    s_state = get_curation_section_state(project, "entities", state_store)
    s_state["focused_node_id"] = str(node_id or "").strip()


def toggle_edge_selection(
    project: dict,
    edge_id: str,
    selected: bool,
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn/bỏ chọn một cạnh theo edge_id (chỉ cho phép chọn cạnh Chờ duyệt / Cần kiểm tra cho thao tác lô)."""
    s_state = get_curation_section_state(project, "edges", state_store)
    eid = str(edge_id or "").strip()
    if not eid:
        return list(s_state["selected_ids"])
    edges_by_id = {str(e.get("id", "")): e for e in project.get("edges", [])}
    edge = edges_by_id.get(eid)
    is_eligible = bool(edge and edge.get("status") in (STATUS_PENDING, STATUS_CHECK))
    return _apply_selection_state(s_state, "toggle", item_id=eid, selected=selected, is_eligible=is_eligible)


def select_page_edges(
    project: dict,
    page_edges: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn các cạnh đủ điều kiện (Chờ duyệt / Cần kiểm tra) trên trang hiện tại, giữ nguyên lựa chọn trang khác."""
    eligible = [str(e["id"]) for e in page_edges if e.get("id") and e.get("status") in (STATUS_PENDING, STATUS_CHECK)]
    return _apply_selection_state(get_curation_section_state(project, "edges", state_store), "select_page", eligible_ids=eligible)


def select_all_filtered_edges(
    project: dict,
    filtered_edges: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn toàn bộ các cạnh đủ điều kiện (Chờ duyệt / Cần kiểm tra) khớp bộ lọc hiện tại."""
    eligible = [str(e["id"]) for e in filtered_edges if e.get("id") and e.get("status") in (STATUS_PENDING, STATUS_CHECK)]
    return _apply_selection_state(get_curation_section_state(project, "edges", state_store), "select_all", eligible_ids=eligible)


def clear_edge_selection(
    project: dict,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Xóa toàn bộ lựa chọn cạnh hiện tại."""
    _apply_selection_state(get_curation_section_state(project, "edges", state_store), "clear")


def reconcile_edge_selection_with_filter(
    project: dict,
    filter_signature: str,
    filtered_edges: list[dict],
    state_store: dict[str, Any] | None = None,
) -> int:
    """Khi bộ lọc thay đổi: tự động bỏ chọn các ID không còn nằm trong kết quả lọc mới và thông báo rõ số mục bị bỏ."""
    visible_eligible_ids = {
        str(e["id"]) for e in filtered_edges if e.get("id") and e.get("status") in (STATUS_PENDING, STATUS_CHECK)
    }
    return _apply_selection_state(
        get_curation_section_state(project, "edges", state_store),
        "reconcile",
        visible_eligible_ids=visible_eligible_ids,
        filter_signature=filter_signature,
        item_noun="cạnh",
    )


def toggle_entity_selection(
    project: dict,
    node_id: str,
    selected: bool,
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn/bỏ chọn một thực thể theo node_id."""
    s_state = get_curation_section_state(project, "entities", state_store)
    nid = str(node_id or "").strip()
    if not nid:
        return list(s_state["selected_ids"])
    is_eligible = any(n.get("id") == nid for n in project.get("nodes", []))
    return _apply_selection_state(s_state, "toggle", item_id=nid, selected=selected, is_eligible=is_eligible)


def select_page_entities(
    project: dict,
    page_nodes: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn các thực thể trên trang hiện tại, giữ nguyên lựa chọn trang khác."""
    eligible = [str(n["id"]) for n in page_nodes if n.get("id")]
    return _apply_selection_state(get_curation_section_state(project, "entities", state_store), "select_page", eligible_ids=eligible)


def select_all_filtered_entities(
    project: dict,
    filtered_nodes: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn toàn bộ các thực thể khớp bộ lọc hiện tại."""
    eligible = [str(n["id"]) for n in filtered_nodes if n.get("id")]
    return _apply_selection_state(get_curation_section_state(project, "entities", state_store), "select_all", eligible_ids=eligible)


def clear_entity_selection(
    project: dict,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Xóa toàn bộ lựa chọn thực thể hiện tại."""
    _apply_selection_state(get_curation_section_state(project, "entities", state_store), "clear")


def reconcile_entity_selection_with_filter(
    project: dict,
    filter_signature: str,
    filtered_nodes: list[dict],
    state_store: dict[str, Any] | None = None,
) -> int:
    """Đồng bộ lựa chọn thực thể khi bộ lọc danh sách thực thể thay đổi."""
    s_state = get_curation_section_state(project, "entities", state_store)
    visible_ids = {str(n.get("id", "")) for n in filtered_nodes if n.get("id")}
    return _apply_selection_state(
        s_state, "reconcile", visible_eligible_ids=visible_ids, filter_signature=filter_signature, item_noun="thực thể"
    )


def get_or_create_edge_draft(
    project: dict,
    edge: dict,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lấy hoặc khởi tạo bản nháp quyết định duyệt/sửa cho một cạnh."""
    s_state = get_curation_section_state(project, "edges", state_store)
    eid = str(edge.get("id", ""))
    if eid not in s_state["drafts"]:
        s_state["drafts"][eid] = {
            "edge_id": eid,
            "action": "approve",
            "reason_code": str(edge.get("rejection_code") or ""),
            "note": str(edge.get("review_note") or ""),
            "override_reason": str(edge.get("override_reason") or ""),
            "self_loop_confirmed": bool(edge.get("self_loop_confirmed", False)),
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            "relation": str(edge.get("relation") or ""),
            "evidence": str(edge.get("evidence") or ""),
            "doc_id": str(edge.get("doc_id") or ""),
        }
    return s_state["drafts"][eid]


def update_edge_draft(
    project: dict,
    edge: dict,
    *,
    state_store: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Cập nhật bản nháp cạnh và hủy hiệu lực bản xem trước lô cạnh."""
    draft = copy.deepcopy(get_or_create_edge_draft(project, edge, state_store=state_store))
    for k, v in fields.items():
        if v is not None:
            draft[k] = v
    s_state = get_curation_section_state(project, "edges", state_store)
    s_state["drafts"][str(edge["id"])] = draft
    invalidate_curation_preview(project, "edges", state_store)
    return draft


def store_curation_edge_preview(
    project: dict,
    preview_dto: CurationPreviewDTO,
    decisions: list[EdgeReviewDecisionDTO],
    *,
    request_id: str = "",
    allow_schema_bypass: bool = False,
    auto_sync_catalog: bool = True,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Lưu kết quả xem trước lô quyết định cạnh vào session state."""
    s_state = get_curation_section_state(project, "edges", state_store)
    s_state["active_preview"] = preview_dto.to_dict()
    s_state["preview_decisions"] = [d.to_dict() for d in decisions]
    s_state["preview_request_id"] = request_id or uid()
    s_state["preview_allow_schema_bypass"] = allow_schema_bypass
    s_state["preview_auto_sync_catalog"] = auto_sync_catalog


def reconcile_edge_state_after_apply(
    project: dict,
    result_dto: CurationResultDTO,
    *,
    current_filtered_ids: set[str] | None = None,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Sau khi áp dụng lô duyệt cạnh: bỏ chọn các cạnh đã áp dụng thành công, giữ lại lựa chọn và bản nháp của cạnh lỗi."""
    s_state = get_curation_section_state(project, "edges", state_store)
    applied_ids = {
        str(item.get("edge_id", ""))
        for item in result_dto.item_results
        if item.get("status") == "applied"
    }
    for eid in applied_ids:
        s_state["drafts"].pop(eid, None)

    remaining = [eid for eid in s_state["selected_ids"] if eid not in applied_ids]
    if current_filtered_ids is not None:
        remaining = [eid for eid in remaining if eid in current_filtered_ids]
    s_state["selected_ids"] = remaining
    s_state["active_preview"] = None
    s_state["preview_decisions"] = []
    s_state["preview_request_id"] = ""
    s_state["preview_allow_schema_bypass"] = False
    s_state["preview_auto_sync_catalog"] = True
    s_state["last_result"] = result_dto.to_dict()


def filter_edges_by_entity(
    project: dict,
    node_id: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Chuyển sang Khu vực A (Quan hệ & bằng chứng) và lọc ngay theo thực thể được chọn từ Khu vực B."""
    set_active_curation_section(project, "edges", state_store)
    e_state = get_curation_section_state(project, "edges", state_store)
    e_state["filters"]["entity_id"] = str(node_id or "all")
    e_state["filters"]["page"] = 1


def stage_entities_for_merge(
    project: dict,
    node_ids: list[str],
    *,
    keep_id: str = "",
    switch_to_merge: bool = True,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Đưa 1 hoặc nhiều thực thể vào bàn gộp ở Khu vực C và khởi tạo gợi ý mặc định an toàn."""
    m_state = get_curation_section_state(project, "merge", state_store)
    nodes_by_id = {str(n.get("id", "")): n for n in project.get("nodes", []) if n.get("id")}
    current = [nid for nid in m_state.get("member_ids", []) if nid in nodes_by_id]
    for nid in node_ids:
        s_nid = str(nid or "").strip()
        if s_nid and s_nid in nodes_by_id and s_nid not in current:
            current.append(s_nid)
    m_state["member_ids"] = current

    if keep_id and keep_id in current:
        m_state["keep_id"] = keep_id
    elif m_state.get("keep_id") not in current:
        m_state["keep_id"] = current[0] if current else ""

    keep_node = nodes_by_id.get(m_state["keep_id"], {})
    if keep_node:
        m_state["canonical_name"] = str(keep_node.get("name") or "")
        m_state["canonical_kind"] = str(keep_node.get("kind") or "")
        descs: list[str] = []
        for nid in current:
            d = str(nodes_by_id[nid].get("description") or "").strip()
            if d and d not in descs:
                descs.append(d)
        m_state["canonical_description"] = "\n".join(descs)

    invalidate_curation_preview(project, "merge", state_store)
    if switch_to_merge:
        set_active_curation_section(project, "merge", state_store)
    return m_state


def update_merge_draft(
    project: dict,
    *,
    state_store: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Cập nhật cấu hình gộp thực thể và hủy hiệu lực kết quả xem trước cũ."""
    m_state = get_curation_section_state(project, "merge", state_store)
    for k, v in fields.items():
        m_state[k] = v
    invalidate_curation_preview(project, "merge", state_store)
    return m_state


def store_entity_merge_preview(
    project: dict,
    preview_dto: EntityMergePreviewDTO,
    *,
    request_id: str = "",
    state_store: dict[str, Any] | None = None,
) -> None:
    """Lưu kết quả xem trước tác động gộp thực thể vào session state."""
    m_state = get_curation_section_state(project, "merge", state_store)
    m_state["active_preview"] = preview_dto.to_dict()
    m_state["preview_request_id"] = request_id or uid()
