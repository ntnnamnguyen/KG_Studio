"""Quản lý trạng thái Bảng Duyệt EDC Hàng Loạt & Ngữ cảnh Điều hướng Liên trang."""
from __future__ import annotations

import copy
from typing import Any

from backend.domain.catalogs.service import catalog_rows, compute_catalog_hash, is_proposal_candidates_stale
from shared.schemas.edc import BulkReviewPreviewDTO, BulkReviewResultDTO, ProposalDecisionDTO
from shared.text_utils import normal, uid
from .core import PAGE_LABELS, _apply_selection_state, _store, bump_sync_nonce
from .curation_state import (
    reset_curation_state_if_project_changed,
    set_active_curation_section,
    set_focused_edge,
    set_focused_entity,
)


def _default_table_state(project_id: str, kind: str) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "kind": kind,
        "selected_ids": [],
        "focused_proposal_id": "",
        "drafts": {},
        "active_preview": None,
        "preview_decisions": [],
        "preview_request_id": "",
        "last_result": None,
        "last_refresh_summary": None,
        "flash_messages": [],
        "filter_prune_notice": "",
        "last_filter_sig": "",
        "filter_nonce": 0,
        "focus_nonce": 0,
        "page_nonce": 0,
        "filters": {
            "status": "pending",
            "search": "",
            "doc_id": "all",
            "candidate_filter": "all",
            "definition_filter": "all",
            "origin_filter": "all",
            "sort_by": "name",
            "sort_desc": False,
            "page_size": 50,
            "page": 1,
        },
    }


def reset_edc_state_if_project_changed(
    project: dict,
    state_store: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> bool:
    """Khi đổi dự án (hoặc force sau khôi phục snapshot): xóa toàn bộ lựa chọn, bản nháp và xem trước."""
    store = _store(state_store)
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    prev_id = store.get("_edc_active_project_id")
    changed = force or (prev_id != proj_id)
    if changed or not isinstance(store.get("_edc_tables"), dict):
        store["_edc_active_project_id"] = proj_id
        store["_edc_tables"] = {
            "entity_types": _default_table_state(proj_id, "entity_types"),
            "relations": _default_table_state(proj_id, "relations"),
        }
        bump_sync_nonce("_inspector_action_nonce", store)
    return changed


def get_edc_table_state(
    project: dict,
    kind: str,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lấy (hoặc khởi tạo) trạng thái bảng EDC độc lập theo `entity_types` / `relations`."""
    if kind not in ("entity_types", "relations"):
        raise ValueError(f"Nhóm bảng EDC không hợp lệ: {kind}")
    store = _store(state_store)
    reset_edc_state_if_project_changed(project, store)
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    tables = store.setdefault("_edc_tables", {})
    if kind not in tables or tables[kind].get("project_id") != proj_id:
        tables[kind] = _default_table_state(proj_id, kind)
    return tables[kind]


def invalidate_active_preview(
    project: dict,
    kind: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Mọi chỉnh sửa bản nháp làm mất hiệu lực kết quả kiểm tra xem trước cũ."""
    t_state = get_edc_table_state(project, kind, state_store)
    t_state["active_preview"] = None
    t_state["preview_decisions"] = []
    t_state["preview_request_id"] = ""


def set_focused_proposal(
    project: dict,
    kind: str,
    proposal_id: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Mở xem chi tiết một dòng mà KHÔNG tự đánh dấu chọn hoặc duyệt dòng đó."""
    t_state = get_edc_table_state(project, kind, state_store)
    t_state["focused_proposal_id"] = str(proposal_id or "").strip()
    t_state["focus_nonce"] = int(t_state.get("focus_nonce") or 0) + 1


def toggle_proposal_selection(
    project: dict,
    kind: str,
    proposal_id: str,
    selected: bool,
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn hoặc bỏ chọn một đề xuất theo ID (chỉ cho phép chọn đề xuất pending cho thao tác lô)."""
    t_state = get_edc_table_state(project, kind, state_store)
    pid = str(proposal_id or "").strip()
    if not pid:
        return list(t_state["selected_ids"])
    proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    prop = proposals_by_id.get(pid)
    is_eligible = bool(prop and prop.get("kind") == kind and prop.get("status") == "pending")
    return _apply_selection_state(t_state, "toggle", item_id=pid, selected=selected, is_eligible=is_eligible)


def select_page_proposals(
    project: dict,
    kind: str,
    page_proposals: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn tất cả các dòng đủ điều kiện (pending) trên trang hiện tại, giữ nguyên lựa chọn ở trang khác."""
    eligible = [str(p["id"]) for p in page_proposals if p.get("id") and p.get("kind") == kind and p.get("status") == "pending"]
    return _apply_selection_state(get_edc_table_state(project, kind, state_store), "select_page", eligible_ids=eligible)


def select_all_filtered_proposals(
    project: dict,
    kind: str,
    filtered_proposals: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn toàn bộ các dòng đủ điều kiện (pending) khớp bộ lọc hiện tại, kể cả ngoài trang đang xem."""
    eligible = [str(p["id"]) for p in filtered_proposals if p.get("id") and p.get("kind") == kind and p.get("status") == "pending"]
    return _apply_selection_state(get_edc_table_state(project, kind, state_store), "select_all", eligible_ids=eligible)


def clear_proposal_selection(
    project: dict,
    kind: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Xóa lựa chọn của riêng bảng hiện tại (không ảnh hưởng bảng kia)."""
    _apply_selection_state(get_edc_table_state(project, kind, state_store), "clear")


def reconcile_selection_with_filter(
    project: dict,
    kind: str,
    filter_signature: str,
    filtered_proposals: list[dict],
    state_store: dict[str, Any] | None = None,
) -> int:
    """Khi bộ lọc thay đổi: loại bỏ các ID không còn nằm trong kết quả lọc mới và thông báo số mục đã bỏ chọn."""
    t_state = get_edc_table_state(project, kind, state_store)
    visible_eligible_ids = {
        str(p.get("id", ""))
        for p in filtered_proposals
        if p.get("id") and p.get("kind") == kind and p.get("status") == "pending"
    }
    return _apply_selection_state(
        t_state, "reconcile", visible_eligible_ids=visible_eligible_ids, filter_signature=filter_signature, item_noun="mục"
    )


def get_or_create_draft(
    project: dict,
    kind: str,
    proposal: dict,
    *,
    default_action: str = "approve",
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lấy hoặc khởi tạo bản nháp quyết định cho 1 đề xuất mà không tự ý chọn Top-1 để commit."""
    t_state = get_edc_table_state(project, kind, state_store)
    pid = str(proposal.get("id", ""))
    if pid not in t_state["drafts"]:
        t_state["drafts"][pid] = ProposalDecisionDTO(
            proposal_id=pid,
            kind=kind,
            action=default_action,
            canonical_name=str(proposal.get("name", "")) if default_action == "approve" else "",
            definition=str(proposal.get("definition", "")),
            description=str(proposal.get("description", "")),
            note=str(proposal.get("review_note", "")),
        ).to_dict()
    return t_state["drafts"][pid]


def update_proposal_draft(
    project: dict,
    kind: str,
    proposal: dict,
    *,
    action: str | None = None,
    canonical_name: str | None = None,
    definition: str | None = None,
    description: str | None = None,
    note: str | None = None,
    state_store: dict[str, Any] | None = None,
    invalidate_preview: bool = True,
) -> dict[str, Any]:
    """Cập nhật bản nháp theo dòng và làm mất hiệu lực preview cũ."""
    draft = dict(get_or_create_draft(project, kind, proposal, state_store=state_store))
    if action is not None:
        draft["action"] = action
        if action == "approve" and not draft.get("canonical_name"):
            draft["canonical_name"] = str(proposal.get("name", ""))
        elif action == "reject":
            draft["canonical_name"] = ""
    if canonical_name is not None:
        draft["canonical_name"] = canonical_name
    if definition is not None:
        draft["definition"] = definition
    if description is not None:
        draft["description"] = description
    if note is not None:
        draft["note"] = note

    t_state = get_edc_table_state(project, kind, state_store)
    t_state["drafts"][str(proposal["id"])] = draft
    if invalidate_preview:
        invalidate_active_preview(project, kind, state_store)
    return draft


def assign_shared_target_to_drafts(
    project: dict,
    kind: str,
    proposal_ids: list[str],
    target_name: str,
    *,
    note: str | None = None,
    state_store: dict[str, Any] | None = None,
) -> int:
    """Điền cùng một đích hợp nhất vào bản nháp của các dòng được chọn (chưa lưu ngay)."""
    proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    updated = 0
    for pid in proposal_ids:
        prop = proposals_by_id.get(str(pid))
        if not prop or prop.get("kind") != kind or prop.get("status") != "pending":
            continue
        update_proposal_draft(
            project,
            kind,
            prop,
            action="merge",
            canonical_name=target_name,
            note=note,
            state_store=state_store,
            invalidate_preview=False,
        )
        updated += 1
    if updated > 0:
        invalidate_active_preview(project, kind, state_store)
    return updated


def fill_top1_candidate_to_drafts(
    project: dict,
    kind: str,
    proposal_ids: list[str],
    *,
    current_model_fingerprint: str = "",
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Điền ứng viên đầu tiên vào bản nháp chỉ cho những dòng có ứng viên còn hợp lệ (không bị stale, đích còn tồn tại)."""
    proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    valid_targets = {normal(r["name"]): r["name"] for r in catalog_rows(project, kind)}
    cat_hash = compute_catalog_hash(project, kind)
    filled_ids: list[str] = []
    skipped: list[dict[str, str]] = []

    for pid in proposal_ids:
        prop = proposals_by_id.get(str(pid))
        if not prop or prop.get("kind") != kind or prop.get("status") != "pending":
            skipped.append({"proposal_id": str(pid), "reason": "Đề xuất không ở trạng thái chờ duyệt"})
            continue
        cands = prop.get("alignment_candidates") or []
        if not cands:
            skipped.append({"proposal_id": str(pid), "reason": "Chưa có ứng viên gợi ý"})
            continue
        stale, stale_reason = is_proposal_candidates_stale(
            project,
            prop,
            current_model_fingerprint,
            precomputed_cat_hash=cat_hash,
        )
        if stale:
            skipped.append({"proposal_id": str(pid), "reason": stale_reason})
            continue
        top_name = str(cands[0].get("name") or "").strip()
        if not top_name or normal(top_name) not in valid_targets:
            skipped.append({"proposal_id": str(pid), "reason": f"Ứng viên '{top_name}' không còn trong danh mục"})
            continue
        canonical = valid_targets[normal(top_name)]
        update_proposal_draft(
            project,
            kind,
            prop,
            action="merge",
            canonical_name=canonical,
            state_store=state_store,
            invalidate_preview=False,
        )
        filled_ids.append(str(pid))

    if filled_ids:
        invalidate_active_preview(project, kind, state_store)

    return {
        "filled_count": len(filled_ids),
        "filled_ids": filled_ids,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }


def prepare_batch_decisions_from_scope(
    project: dict,
    kind: str,
    proposal_ids: list[str],
    *,
    batch_action: str | None = None,
    shared_note: str = "",
    state_store: dict[str, Any] | None = None,
) -> list[ProposalDecisionDTO]:
    """Đóng gói danh sách ProposalDecisionDTO cho tập ID đã chốt (dùng tên/định nghĩa riêng từng mục khi duyệt mới)."""
    t_state = get_edc_table_state(project, kind, state_store)
    proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    locked_ids = list(dict.fromkeys(str(pid).strip() for pid in proposal_ids if str(pid).strip()))
    decisions: list[ProposalDecisionDTO] = []

    for pid in locked_ids:
        prop = proposals_by_id.get(pid)
        if prop is None:
            decisions.append(
                ProposalDecisionDTO(
                    proposal_id=pid,
                    kind=kind,
                    action=batch_action or "approve",
                )
            )
            continue

        draft = copy.deepcopy(get_or_create_draft(project, kind, prop, state_store=state_store))
        effective_action = batch_action if batch_action in ("approve", "merge", "reject") else draft.get("action", "approve")

        if effective_action == "approve":
            canon = str(draft.get("canonical_name") or "").strip()
            if not canon or draft.get("action") != "approve":
                canon = str(prop.get("name", "")).strip()
            defn = str(draft.get("definition") or "").strip() or str(prop.get("definition", "")).strip()
            desc = str(draft.get("description") or "").strip() or str(prop.get("description", "")).strip()
        elif effective_action == "merge":
            canon = str(draft.get("canonical_name") or "").strip() if draft.get("action") == "merge" else ""
            defn = str(draft.get("definition") or "").strip() or str(prop.get("definition", "")).strip()
            desc = str(draft.get("description") or "").strip()
        else:
            canon = ""
            defn = str(draft.get("definition") or "").strip() or str(prop.get("definition", "")).strip()
            desc = ""

        note = str(draft.get("note") or "").strip() or shared_note.strip()
        updated_draft = ProposalDecisionDTO(
            proposal_id=pid,
            kind=kind,
            action=effective_action,
            canonical_name=canon,
            definition=defn,
            description=desc,
            note=note,
        )
        t_state["drafts"][pid] = updated_draft.to_dict()
        decisions.append(updated_draft)

    return decisions


def store_active_preview(
    project: dict,
    kind: str,
    preview_dto: BulkReviewPreviewDTO,
    decisions: list[ProposalDecisionDTO],
    *,
    request_id: str = "",
    state_store: dict[str, Any] | None = None,
) -> None:
    """Lưu kết quả xem trước duyệt lô EDC vào session state."""
    t_state = get_edc_table_state(project, kind, state_store)
    t_state["active_preview"] = preview_dto.to_dict()
    t_state["preview_decisions"] = [d.to_dict() for d in decisions]
    t_state["preview_request_id"] = request_id or uid()


def reconcile_state_after_apply(
    project: dict,
    kind: str,
    result_dto: BulkReviewResultDTO,
    *,
    current_filtered_ids: set[str] | None = None,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Sau khi commit: bỏ chọn các mục đã áp dụng thành công; giữ lựa chọn và bản nháp của mục lỗi/chưa xử lý."""
    t_state = get_edc_table_state(project, kind, state_store)
    applied_ids = {
        str(item.get("proposal_id", ""))
        for item in result_dto.item_results
        if item.get("status") == "applied"
    }
    for pid in applied_ids:
        t_state["drafts"].pop(pid, None)

    remaining_selected = [pid for pid in t_state["selected_ids"] if pid not in applied_ids]
    if current_filtered_ids is not None:
        remaining_selected = [pid for pid in remaining_selected if pid in current_filtered_ids]
    t_state["selected_ids"] = remaining_selected
    t_state["sel_editor_nonce"] = int(t_state.get("sel_editor_nonce") or 0) + 1
    t_state["active_preview"] = None
    t_state["preview_decisions"] = []
    t_state["preview_request_id"] = ""
    t_state["last_result"] = result_dto.to_dict()


def navigate_to_edc_proposal_from_curation(
    project: dict,
    proposal_id: str,
    *,
    edge_id: str = "",
    node_id: str = "",
    section: str = "edges",
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Điều hướng từ phân khu kiểm duyệt sang đúng bảng và proposal_id ở tab EDC, lưu ngữ cảnh quay lại."""
    store = _store(state_store)
    reset_edc_state_if_project_changed(project, store)
    reset_curation_state_if_project_changed(project, store)

    pid = str(proposal_id or "").strip()
    prop = next((p for p in project.get("schema_proposals", []) if str(p.get("id", "")) == pid), None)
    kind = str(prop.get("kind", "relations")) if prop else "relations"
    if kind not in ("entity_types", "relations"):
        kind = "relations"

    set_focused_proposal(project, kind, pid, store)
    t_state = get_edc_table_state(project, kind, store)
    if prop and prop.get("status") != t_state["filters"].get("status") and t_state["filters"].get("status") != "all":
        t_state["filters"]["status"] = "all"
        t_state["filters"]["page"] = 1
        t_state["filter_nonce"] = int(t_state.get("filter_nonce") or 0) + 1
        t_state["page_nonce"] = int(t_state.get("page_nonce") or 0) + 1

    return_ctx = {
        "project_id": str(project.get("project_id") or project.get("name") or "default"),
        "proposal_id": pid,
        "kind": kind,
        "section": section if section in ("edges", "entities", "merge") else "edges",
        "edge_id": str(edge_id or ""),
        "node_id": str(node_id or ""),
    }
    store["_curation_return_context"] = return_ctx
    store["active_page"] = PAGE_LABELS[3]
    store["active_step"] = "review"
    store["curation_hub_active_tab"] = "schema"
    bump_sync_nonce("_nav_sync_nonce", store)
    bump_sync_nonce("_curation_hub_tab_nonce", store)
    return return_ctx


def return_to_curation_from_edc(
    project: dict,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Quay lại đúng phân khu và mục (cạnh/thực thể) đang kiểm duyệt sau khi xử lý xong lược đồ."""
    store = _store(state_store)
    ctx = store.get("_curation_return_context")
    if not isinstance(ctx, dict):
        store["active_page"] = PAGE_LABELS[3]
        store["active_step"] = "review"
        set_active_curation_section(project, "edges", store)
        bump_sync_nonce("_nav_sync_nonce", store)
        return None
    section = str(ctx.get("section") or "edges")
    set_active_curation_section(project, section, store)
    if ctx.get("edge_id"):
        set_focused_edge(project, str(ctx["edge_id"]), store)
    if ctx.get("node_id"):
        set_focused_entity(project, str(ctx["node_id"]), store)
    store["active_page"] = PAGE_LABELS[3]
    store["active_step"] = "review"
    bump_sync_nonce("_nav_sync_nonce", store)
    store["_curation_return_context"] = None
    return ctx
