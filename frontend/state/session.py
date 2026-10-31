"""Quản lý Session State tập trung cho Streamlit UI và Trạng thái Duyệt EDC Hàng Loạt."""
from __future__ import annotations

import copy
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows, is_proposal_candidates_stale
from backend.facade import get_facade
from backend.integrations.llm_gateway import LLMGateway
from shared.config_loader import CONFIG
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING
from shared.schemas.curation import (
    CurationPreviewDTO,
    CurationResultDTO,
    EdgeReviewDecisionDTO,
    EntityMergePreviewDTO,
)
from shared.schemas.edc import BulkReviewPreviewDTO, BulkReviewResultDTO, ProposalDecisionDTO
from shared.secrets_manager import delete_api_key, get_api_key, has_persisted_key, mask_api_key, save_api_key
from shared.text_utils import normal, uid
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


def compute_pipeline_readiness(project: dict) -> dict[str, Any]:
    """Đánh giá điều kiện sẵn sàng, tiến độ và hành động gợi ý tiếp theo cho quy trình 5 bước."""
    docs = project.get("documents", [])
    runs = project.get("runs", [])
    nodes = project.get("nodes", [])
    edges = project.get("edges", [])
    proposals = project.get("schema_proposals", [])
    errors = project.get("chunk_errors", {})

    # 1. Tài liệu
    has_docs = len(docs) > 0
    total_chars = sum(int(d.get("chars", len(d.get("text", "")))) for d in docs)
    doc_state = "ready" if has_docs else "empty"
    doc_badge = "✓" if has_docs else "○"

    # 2. Thiết lập
    has_rel_cat = bool(project.get("relations"))
    has_type_cat = bool(project.get("entity_types"))
    setup_ready = has_rel_cat and has_type_cat
    setup_state = "ready" if setup_ready else "warning"
    setup_badge = "✓" if setup_ready else "!"

    # 3. Trích xuất
    has_runs = len(runs) > 0
    has_errors = len(errors) > 0
    if has_errors:
        ext_state = "partial_failed"
        ext_badge = "!"
    elif has_runs:
        ext_state = "done"
        ext_badge = "✓"
    else:
        ext_state = "empty"
        ext_badge = "○"

    # 4. Rà soát
    approved_count = sum(1 for e in edges if e.get("status") == STATUS_APPROVED)
    pending_edges = sum(1 for e in edges if e.get("status") == STATUS_PENDING)
    check_edges = sum(1 for e in edges if e.get("status") == STATUS_CHECK)
    pending_props = sum(1 for p in proposals if p.get("status") == "pending")
    total_needs_review = pending_edges + check_edges + pending_props

    if total_needs_review > 0:
        rev_state = "pending_work"
        rev_badge = "●"
    elif approved_count > 0:
        rev_state = "clean"
        rev_badge = "✓"
    else:
        rev_state = "empty"
        rev_badge = "○"

    # 5. Khai thác
    has_approved = approved_count > 0
    exp_state = "ready" if has_approved else "empty"
    exp_badge = "✓" if has_approved else "○"

    # Xác định hành động tiếp theo tổng thể của dự án
    if not has_docs:
        overall_next = {
            "step_id": "documents",
            "step_index": 0,
            "title": "Tải tài liệu nguồn đầu tiên",
            "reason": "Dự án chưa có tài liệu văn bản để trích xuất tri thức.",
            "button_text": "➡️ Thêm tài liệu ở Bước 1",
        }
    elif not has_runs:
        overall_next = {
            "step_id": "extraction",
            "step_index": 2,
            "title": "Bắt đầu trích xuất tri thức",
            "reason": f"Đã có {len(docs)} tài liệu sẵn sàng. Chạy trích xuất thực thể & quan hệ.",
            "button_text": "➡️ Bắt đầu trích xuất ở Bước 3",
        }
    elif has_errors:
        overall_next = {
            "step_id": "extraction",
            "step_index": 2,
            "title": f"Xử lý {len(errors)} đoạn văn bản gặp lỗi",
            "reason": "Có đoạn trích xuất gặp sự cố kết nối hoặc giới hạn token.",
            "button_text": "➡️ Xem và chạy lại đoạn lỗi ở Bước 3",
        }
    elif total_needs_review > 0:
        overall_next = {
            "step_id": "review",
            "step_index": 3,
            "title": f"Rà soát {total_needs_review} mục dữ kiện & thuật ngữ",
            "reason": f"Còn {pending_edges} quan hệ chờ duyệt và {pending_props} đề xuất danh mục.",
            "button_text": "➡️ Rà soát dữ kiện ở Bước 4",
        }
    elif has_approved:
        overall_next = {
            "step_id": "explore",
            "step_index": 4,
            "title": "Khai thác đồ thị & Xuất dữ liệu",
            "reason": f"Toàn bộ {approved_count} dữ kiện đã được duyệt hợp lệ 100%.",
            "button_text": "➡️ Khai thác & Xuất đồ thị ở Bước 5",
        }
    else:
        overall_next = {
            "step_id": "documents",
            "step_index": 0,
            "title": "Thêm tài liệu nghiên cứu mới",
            "reason": "Dự án đã hoàn tất các dữ kiện hiện có.",
            "button_text": "➡️ Thêm tài liệu mới ở Bước 1",
        }

    return {
        "documents": {
            "state": doc_state,
            "badge": doc_badge,
            "ready": has_docs,
            "count": len(docs),
            "total_chars": total_chars,
        },
        "setup": {
            "state": setup_state,
            "badge": setup_badge,
            "ready": setup_ready,
            "mode": project.get("extraction_mode", "closed"),
        },
        "extraction": {
            "state": ext_state,
            "badge": ext_badge,
            "ready": has_runs and not has_errors,
            "runs_count": len(runs),
            "errors_count": len(errors),
        },
        "review": {
            "state": rev_state,
            "badge": rev_badge,
            "ready": total_needs_review == 0 and approved_count > 0,
            "pending_edges": pending_edges,
            "check_edges": check_edges,
            "pending_props": pending_props,
            "needs_review_count": total_needs_review,
            "approved_count": approved_count,
        },
        "explore": {
            "state": exp_state,
            "badge": exp_badge,
            "ready": has_approved,
            "approved_count": approved_count,
            "nodes_count": len(nodes),
            "edges_count": len(edges),
        },
        "overall_next": overall_next,
    }


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


def _store(state_store: dict[str, Any] | None = None) -> Any:
    return state_store if state_store is not None else st.session_state


def reset_edc_state_if_project_changed(project: dict, state_store: dict[str, Any] | None = None) -> bool:
    """Khi đổi dự án: xóa toàn bộ lựa chọn, bản nháp và kết quả xem trước của dự án trước."""
    store = _store(state_store)
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    prev_id = store.get("_edc_active_project_id")
    if prev_id != proj_id:
        store["_edc_active_project_id"] = proj_id
        store["_edc_tables"] = {
            "entity_types": _default_table_state(proj_id, "entity_types"),
            "relations": _default_table_state(proj_id, "relations"),
        }
        return True
    if "_edc_tables" not in store or not isinstance(store["_edc_tables"], dict):
        store["_edc_tables"] = {
            "entity_types": _default_table_state(proj_id, "entity_types"),
            "relations": _default_table_state(proj_id, "relations"),
        }
    return False


def get_edc_table_state(
    project: dict,
    kind: str,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    t_state["selected_ids"] = toggle_id_in_list(t_state["selected_ids"], pid, selected, is_eligible)
    return list(t_state["selected_ids"])


def select_page_proposals(
    project: dict,
    kind: str,
    page_proposals: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn tất cả các dòng đủ điều kiện (pending) trên trang hiện tại, giữ nguyên lựa chọn ở trang khác."""
    t_state = get_edc_table_state(project, kind, state_store)
    eligible_ids = [
        str(prop.get("id", ""))
        for prop in page_proposals
        if prop.get("id") and prop.get("kind") == kind and prop.get("status") == "pending"
    ]
    t_state["selected_ids"] = append_unique_ids(t_state["selected_ids"], eligible_ids)
    return list(t_state["selected_ids"])


def select_all_filtered_proposals(
    project: dict,
    kind: str,
    filtered_proposals: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn toàn bộ các dòng đủ điều kiện (pending) khớp bộ lọc hiện tại, kể cả ngoài trang đang xem."""
    t_state = get_edc_table_state(project, kind, state_store)
    eligible = [
        str(prop.get("id", ""))
        for prop in filtered_proposals
        if prop.get("id") and prop.get("kind") == kind and prop.get("status") == "pending"
    ]
    t_state["selected_ids"] = list(dict.fromkeys(eligible))
    return list(t_state["selected_ids"])


def clear_proposal_selection(
    project: dict,
    kind: str,
    state_store: dict[str, Any] | None = None,
) -> None:
    """Xóa lựa chọn của riêng bảng hiện tại (không ảnh hưởng bảng kia)."""
    t_state = get_edc_table_state(project, kind, state_store)
    t_state["selected_ids"] = []
    t_state["filter_prune_notice"] = ""


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
    prev_sig = t_state.get("last_filter_sig", "")
    t_state["last_filter_sig"] = filter_signature
    kept, pruned_count, notice = reconcile_id_selection(
        t_state["selected_ids"], visible_eligible_ids, prev_sig, filter_signature, item_noun="mục"
    )
    t_state["selected_ids"] = kept
    t_state["filter_prune_notice"] = notice
    return pruned_count


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
) -> dict[str, Any]:
    """Cập nhật bản nháp theo dòng và làm mất hiệu lực preview cũ."""
    draft = copy.deepcopy(get_or_create_draft(project, kind, proposal, state_store=state_store))
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
        )
        updated += 1
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
        stale, stale_reason = is_proposal_candidates_stale(project, prop, current_model_fingerprint)
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
        )
        filled_ids.append(str(pid))

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
            # Luôn dùng tên và định nghĩa riêng của từng mục nếu bản nháp đang rỗng hoặc trước đó là merge/reject
            canon = str(draft.get("canonical_name") or "").strip()
            if not canon or draft.get("action") != "approve":
                canon = str(prop.get("name", "")).strip()
            defn = str(draft.get("definition") or "").strip() or str(prop.get("definition", "")).strip()
            desc = str(draft.get("description") or "").strip() or str(prop.get("description", "")).strip()
        elif effective_action == "merge":
            # Không bao giờ tự động chọn Top-1 để commit nếu người dùng chưa điền vào bản nháp
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
    t_state["active_preview"] = None
    t_state["preview_decisions"] = []
    t_state["preview_request_id"] = ""
    t_state["last_result"] = result_dto.to_dict()


# ==============================================================================
# QUẢN LÝ TRẠNG THÁI TRANG 5: KIỂM DUYỆT & GỘP THỰC THỂ (edges / entities / merge)
# ==============================================================================


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
    if prev_id != proj_id:
        store["_curation_active_project_id"] = proj_id
        store["_curation_active_section"] = "edges"
        store["_curation_return_context"] = None
        store["_curation_sections"] = {
            "edges": _default_curation_section_state(proj_id, "edges"),
            "entities": _default_curation_section_state(proj_id, "entities"),
            "merge": _default_curation_section_state(proj_id, "merge"),
        }
        return True
    if "_curation_sections" not in store or not isinstance(store["_curation_sections"], dict):
        store["_curation_sections"] = {
            "edges": _default_curation_section_state(proj_id, "edges"),
            "entities": _default_curation_section_state(proj_id, "entities"),
            "merge": _default_curation_section_state(proj_id, "merge"),
        }
    return False


def get_curation_section_state(
    project: dict,
    section: str,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    store = _store(state_store)
    reset_curation_state_if_project_changed(project, store)
    sec = str(store.get("_curation_active_section") or "edges")
    return sec if sec in ("edges", "entities", "merge") else "edges"


def set_active_curation_section(
    project: dict,
    section: str,
    state_store: dict[str, Any] | None = None,
) -> None:
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
    s_state["selected_ids"] = toggle_id_in_list(s_state["selected_ids"], eid, selected, is_eligible)
    return list(s_state["selected_ids"])


def select_page_edges(
    project: dict,
    page_edges: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn các cạnh đủ điều kiện (Chờ duyệt / Cần kiểm tra) trên trang hiện tại, giữ nguyên lựa chọn trang khác."""
    s_state = get_curation_section_state(project, "edges", state_store)
    eligible_ids = [
        str(edge.get("id", ""))
        for edge in page_edges
        if edge.get("id") and edge.get("status") in (STATUS_PENDING, STATUS_CHECK)
    ]
    s_state["selected_ids"] = append_unique_ids(s_state["selected_ids"], eligible_ids)
    return list(s_state["selected_ids"])


def select_all_filtered_edges(
    project: dict,
    filtered_edges: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn toàn bộ các cạnh đủ điều kiện (Chờ duyệt / Cần kiểm tra) khớp bộ lọc hiện tại."""
    s_state = get_curation_section_state(project, "edges", state_store)
    eligible = [
        str(edge.get("id", ""))
        for edge in filtered_edges
        if edge.get("id") and edge.get("status") in (STATUS_PENDING, STATUS_CHECK)
    ]
    s_state["selected_ids"] = list(dict.fromkeys(eligible))
    return list(s_state["selected_ids"])


def clear_edge_selection(
    project: dict,
    state_store: dict[str, Any] | None = None,
) -> None:
    s_state = get_curation_section_state(project, "edges", state_store)
    s_state["selected_ids"] = []
    s_state["filter_prune_notice"] = ""


def reconcile_edge_selection_with_filter(
    project: dict,
    filter_signature: str,
    filtered_edges: list[dict],
    state_store: dict[str, Any] | None = None,
) -> int:
    """Khi bộ lọc thay đổi: tự động bỏ chọn các ID không còn nằm trong kết quả lọc mới và thông báo rõ số mục bị bỏ."""
    s_state = get_curation_section_state(project, "edges", state_store)
    visible_eligible_ids = {
        str(e.get("id", ""))
        for e in filtered_edges
        if e.get("id") and e.get("status") in (STATUS_PENDING, STATUS_CHECK)
    }
    prev_sig = s_state.get("last_filter_sig", "")
    s_state["last_filter_sig"] = filter_signature
    kept, pruned_count, notice = reconcile_id_selection(
        s_state["selected_ids"], visible_eligible_ids, prev_sig, filter_signature, item_noun="cạnh"
    )
    s_state["selected_ids"] = kept
    s_state["filter_prune_notice"] = notice
    return pruned_count


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
    nodes_by_id = {str(n.get("id", "")): n for n in project.get("nodes", [])}
    is_eligible = nid in nodes_by_id
    s_state["selected_ids"] = toggle_id_in_list(s_state["selected_ids"], nid, selected, is_eligible)
    return list(s_state["selected_ids"])


def select_page_entities(
    project: dict,
    page_nodes: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn các thực thể trên trang hiện tại, giữ nguyên lựa chọn trang khác."""
    s_state = get_curation_section_state(project, "entities", state_store)
    node_ids = [str(node.get("id", "")) for node in page_nodes if node.get("id")]
    s_state["selected_ids"] = append_unique_ids(s_state["selected_ids"], node_ids)
    return list(s_state["selected_ids"])


def select_all_filtered_entities(
    project: dict,
    filtered_nodes: list[dict],
    state_store: dict[str, Any] | None = None,
) -> list[str]:
    """Chọn toàn bộ các thực thể khớp bộ lọc hiện tại."""
    s_state = get_curation_section_state(project, "entities", state_store)
    node_ids = [str(node.get("id", "")) for node in filtered_nodes if node.get("id")]
    s_state["selected_ids"] = list(dict.fromkeys(node_ids))
    return list(s_state["selected_ids"])


def clear_entity_selection(
    project: dict,
    state_store: dict[str, Any] | None = None,
) -> None:
    s_state = get_curation_section_state(project, "entities", state_store)
    s_state["selected_ids"] = []
    s_state["filter_prune_notice"] = ""


def reconcile_entity_selection_with_filter(
    project: dict,
    filter_signature: str,
    filtered_nodes: list[dict],
    state_store: dict[str, Any] | None = None,
) -> int:
    s_state = get_curation_section_state(project, "entities", state_store)
    visible_ids = {str(n.get("id", "")) for n in filtered_nodes if n.get("id")}
    prev_sig = s_state.get("last_filter_sig", "")
    s_state["last_filter_sig"] = filter_signature
    kept, pruned_count, notice = reconcile_id_selection(
        s_state["selected_ids"], visible_ids, prev_sig, filter_signature, item_noun="thực thể"
    )
    s_state["selected_ids"] = kept
    s_state["filter_prune_notice"] = notice
    return pruned_count


def get_or_create_edge_draft(
    project: dict,
    edge: dict,
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        # Gộp mô tả mặc định nếu có
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
    m_state = get_curation_section_state(project, "merge", state_store)
    m_state["active_preview"] = preview_dto.to_dict()
    m_state["preview_request_id"] = request_id or uid()


def navigate_to_edc_proposal_from_curation(
    project: dict,
    proposal_id: str,
    *,
    edge_id: str = "",
    node_id: str = "",
    section: str = "edges",
    state_store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Điều hướng từ Trang 5 sang đúng bảng và proposal_id ở Trang 4, lưu ngữ cảnh quay lại Trang 5."""
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
    # Bảo đảm bộ lọc ở Trang 4 không ẩn đề xuất đang cần kiểm tra
    if prop and prop.get("status") != t_state["filters"].get("status") and t_state["filters"].get("status") != "all":
        t_state["filters"]["status"] = "all"

    return_ctx = {
        "project_id": str(project.get("project_id") or project.get("name") or "default"),
        "proposal_id": pid,
        "kind": kind,
        "section": section if section in ("edges", "entities", "merge") else "edges",
        "edge_id": str(edge_id or ""),
        "node_id": str(node_id or ""),
    }
    store["_curation_return_context"] = return_ctx
    store["active_page"] = PAGE_LABELS[3]  # "4. Kiểm duyệt & Chuẩn hóa Tri thức"
    store["curation_hub_active_tab"] = "schema"
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
        store["curation_hub_active_tab"] = "edges"
        return None
    section = str(ctx.get("section") or "edges")
    set_active_curation_section(project, section, store)
    if ctx.get("edge_id"):
        set_focused_edge(project, str(ctx["edge_id"]), store)
    if ctx.get("node_id"):
        set_focused_entity(project, str(ctx["node_id"]), store)
    store["active_page"] = PAGE_LABELS[3]  # "4. Kiểm duyệt & Chuẩn hóa Tri thức"
    store["curation_hub_active_tab"] = "edges" if section == "edges" else "entities"
    store["_curation_return_context"] = None
    return ctx


def ensure_session_state() -> dict:
    facade = get_facade()
    if "active_project_name" not in st.session_state:
        projects = facade.list_projects()
        default_name = projects[0] if projects else CONFIG["app"]["default_project_name"]
        st.session_state["active_project_name"] = default_name

    if "project" not in st.session_state or st.session_state.get("_loaded_name") != st.session_state["active_project_name"]:
        proj = facade.load_project(st.session_state["active_project_name"])
        st.session_state["project"] = proj
        st.session_state["_loaded_name"] = proj["name"]
        reset_edc_state_if_project_changed(proj, st.session_state)
        reset_curation_state_if_project_changed(proj, st.session_state)
    else:
        reset_edc_state_if_project_changed(st.session_state["project"], st.session_state)
        reset_curation_state_if_project_changed(st.session_state["project"], st.session_state)

    st.session_state.setdefault("active_page", PAGE_LABELS[0])
    cur_provider = st.session_state.setdefault("llm_provider", LLMGateway.DEFAULT_PROVIDER)
    st.session_state.setdefault("llm_model", LLMGateway.DEFAULT_MODELS.get(cur_provider, "deepseek-chat"))
    st.session_state.setdefault("llm_base_url", LLMGateway.resolve_base_url(cur_provider))

    # Nạp API key an toàn từ secrets manager nếu chưa có
    if "llm_api_key" not in st.session_state or not st.session_state["llm_api_key"]:
        persisted_key = get_api_key(cur_provider)
        st.session_state["llm_api_key"] = persisted_key
    else:
        st.session_state.setdefault("llm_api_key", "")

    rec_tok = LLMGateway.recommend_token_limits(
        st.session_state["llm_provider"],
        st.session_state["llm_model"],
    )
    st.session_state.setdefault("llm_max_input_tokens", int(CONFIG.get("llm", {}).get("max_input_tokens", rec_tok["max_input_tokens"])))
    st.session_state.setdefault("llm_max_output_tokens", int(CONFIG.get("llm", {}).get("max_tokens", rec_tok["max_output_tokens"])))
    st.session_state.setdefault("extraction_chunk_size", int(CONFIG.get("extraction", {}).get("chunk_size", rec_tok["recommended_chunk_size"])))

    # Khởi tạo giá trị ban đầu cho các widget keys để tránh lỗi rỗng
    for k, v in [
        ("sb_llm_key", st.session_state["llm_api_key"]),
        ("p02_llm_key", st.session_state["llm_api_key"]),
        ("sb_llm_model", st.session_state["llm_model"]),
        ("p02_llm_model", st.session_state["llm_model"]),
        ("sb_llm_url", st.session_state["llm_base_url"]),
        ("p02_llm_url", st.session_state["llm_base_url"]),
        ("sb_llm_max_in", st.session_state["llm_max_input_tokens"]),
        ("p02_llm_max_in", st.session_state["llm_max_input_tokens"]),
        ("sb_llm_max_out", st.session_state["llm_max_output_tokens"]),
        ("p02_llm_max_out", st.session_state["llm_max_output_tokens"]),
    ]:
        st.session_state.setdefault(k, v)

    return st.session_state["project"]


def sync_llm_state_from_store() -> None:
    """Đồng bộ giá trị từ canonical session_state sang các widget keys (sb_* và p02_*)."""
    k = st.session_state.get("llm_api_key", "")
    st.session_state["sb_llm_key"] = k
    st.session_state["p02_llm_key"] = k

    m = st.session_state.get("llm_model", "")
    st.session_state["sb_llm_model"] = m
    st.session_state["p02_llm_model"] = m

    u = st.session_state.get("llm_base_url", "")
    st.session_state["sb_llm_url"] = u
    st.session_state["p02_llm_url"] = u

    p = st.session_state.get("llm_provider", LLMGateway.DEFAULT_PROVIDER)
    st.session_state["sb_llm_provider"] = p
    st.session_state["p02_llm_prov"] = p

    mi = int(st.session_state.get("llm_max_input_tokens", 16000))
    st.session_state["sb_llm_max_in"] = mi
    st.session_state["p02_llm_max_in"] = mi

    mo = int(st.session_state.get("llm_max_output_tokens", 16384))
    st.session_state["sb_llm_max_out"] = mo
    st.session_state["p02_llm_max_out"] = mo


def on_sb_llm_key_change() -> None:
    val = str(st.session_state.get("sb_llm_key", "")).strip()
    st.session_state["llm_api_key"] = val
    st.session_state["p02_llm_key"] = val


def on_p02_llm_key_change() -> None:
    val = str(st.session_state.get("p02_llm_key", "")).strip()
    st.session_state["llm_api_key"] = val
    st.session_state["sb_llm_key"] = val


def on_sb_llm_model_change() -> None:
    val = str(st.session_state.get("sb_llm_model", "")).strip()
    st.session_state["llm_model"] = val
    st.session_state["p02_llm_model"] = val


def on_p02_llm_model_change() -> None:
    val = str(st.session_state.get("p02_llm_model", "")).strip()
    st.session_state["llm_model"] = val
    st.session_state["sb_llm_model"] = val


def on_sb_llm_url_change() -> None:
    val = str(st.session_state.get("sb_llm_url", "")).strip()
    st.session_state["llm_base_url"] = val
    st.session_state["p02_llm_url"] = val


def on_p02_llm_url_change() -> None:
    val = str(st.session_state.get("p02_llm_url", "")).strip()
    st.session_state["llm_base_url"] = val
    st.session_state["sb_llm_url"] = val


def on_sb_llm_max_in_change() -> None:
    val = int(st.session_state.get("sb_llm_max_in", 16000))
    st.session_state["llm_max_input_tokens"] = val
    st.session_state["p02_llm_max_in"] = val


def on_p02_llm_max_in_change() -> None:
    val = int(st.session_state.get("p02_llm_max_in", 16000))
    st.session_state["llm_max_input_tokens"] = val
    st.session_state["sb_llm_max_in"] = val


def on_sb_llm_max_out_change() -> None:
    val = int(st.session_state.get("sb_llm_max_out", 16384))
    st.session_state["llm_max_output_tokens"] = val
    st.session_state["p02_llm_max_out"] = val


def on_p02_llm_max_out_change() -> None:
    val = int(st.session_state.get("p02_llm_max_out", 16384))
    st.session_state["llm_max_output_tokens"] = val
    st.session_state["sb_llm_max_out"] = val


def switch_llm_provider(new_provider: str) -> None:
    """Chuyển đổi nhà cung cấp LLM: cập nhật provider, model, URL, nạp API key đã lưu và đề xuất token."""
    if new_provider not in LLMGateway.PROVIDERS:
        return
    st.session_state["llm_provider"] = new_provider
    st.session_state["sb_llm_provider"] = new_provider
    st.session_state["p02_llm_prov"] = new_provider

    new_model = LLMGateway.DEFAULT_MODELS.get(new_provider, "")
    st.session_state["llm_model"] = new_model
    st.session_state["sb_llm_model"] = new_model
    st.session_state["p02_llm_model"] = new_model

    new_url = LLMGateway.resolve_base_url(new_provider)
    st.session_state["llm_base_url"] = new_url
    st.session_state["sb_llm_url"] = new_url
    st.session_state["p02_llm_url"] = new_url

    # Nạp API key an toàn cho provider mới
    saved_key = get_api_key(new_provider)
    st.session_state["llm_api_key"] = saved_key
    st.session_state["sb_llm_key"] = saved_key
    st.session_state["p02_llm_key"] = saved_key

    auto_rec = LLMGateway.recommend_token_limits(new_provider, new_model)
    st.session_state["llm_max_input_tokens"] = auto_rec["max_input_tokens"]
    st.session_state["sb_llm_max_in"] = auto_rec["max_input_tokens"]
    st.session_state["p02_llm_max_in"] = auto_rec["max_input_tokens"]

    st.session_state["llm_max_output_tokens"] = auto_rec["max_output_tokens"]
    st.session_state["sb_llm_max_out"] = auto_rec["max_output_tokens"]
    st.session_state["p02_llm_max_out"] = auto_rec["max_output_tokens"]

    st.session_state["extraction_chunk_size"] = auto_rec["recommended_chunk_size"]
