"""Logic xây dựng bản xem trước và thực thi áp dụng lô quyết định cho EDC."""
from __future__ import annotations

from typing import Any

from backend.domain.catalogs.service import compute_project_revision
from frontend.client import FrontendClient, get_client
from frontend.state.session import (
    get_edc_table_state,
    prepare_batch_decisions_from_scope,
    reconcile_state_after_apply,
    store_active_preview,
)
from shared.schemas.edc import (
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
    ProposalDecisionDTO,
)
from shared.text_utils import uid


def build_preview_for_scope(
    project: dict,
    kind: str,
    proposal_ids: list[str],
    *,
    batch_action: str | None = None,
    shared_note: str = "",
    filter_summary: dict[str, Any] | None = None,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> BulkReviewPreviewDTO:
    """Chốt danh sách ID tại thời điểm xem trước, tạo bản nháp và gọi backend preview_proposal_decisions."""
    svc = client or get_client()
    decisions = prepare_batch_decisions_from_scope(
        project,
        kind,
        proposal_ids,
        batch_action=batch_action,
        shared_note=shared_note,
        state_store=state_store,
    )
    req_id = uid()
    req = BulkReviewRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        kind=kind,
        expected_revision=compute_project_revision(project),
        request_id=req_id,
        decisions=decisions,
        apply_mode="all_or_nothing",
        filter_summary=dict(filter_summary or {}),
    )
    preview = svc.preview_proposal_decisions(project, req)
    store_active_preview(project, kind, preview, decisions, request_id=req_id, state_store=state_store)
    return preview


def execute_batch_apply(
    project: dict,
    kind: str,
    *,
    apply_mode: str = "all_or_nothing",
    current_filtered_ids: set[str] | None = None,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> BulkReviewResultDTO:
    """Thực thi commit lô quyết định đã xem trước và cập nhật lại session state."""
    svc = client or get_client()
    t_state = get_edc_table_state(project, kind, state_store)
    active_prev_raw = t_state.get("active_preview")
    if not active_prev_raw:
        raise ValueError("Chưa có bản xem trước hợp lệ. Vui lòng chạy 'Xem trước quyết định' trước khi áp dụng.")

    preview_dto = BulkReviewPreviewDTO.from_dict(active_prev_raw)
    decisions = [ProposalDecisionDTO.from_dict(d) for d in t_state.get("preview_decisions", [])]
    req_id = str(t_state.get("preview_request_id") or uid())

    req = BulkReviewRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        kind=kind,
        expected_revision=preview_dto.revision,
        request_id=req_id,
        decisions=decisions,
        apply_mode=apply_mode,
        filter_summary=dict(t_state.get("filters") or {}),
    )
    result = svc.apply_proposal_decisions(project, req, preview=preview_dto)
    reconcile_state_after_apply(
        project,
        kind,
        result,
        current_filtered_ids=current_filtered_ids,
        state_store=state_store,
    )
    return result


def quick_apply_proposal_batch(
    project: dict,
    kind: str,
    proposal_ids: list[str],
    batch_action: str,
    *,
    shared_note: str = "",
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> BulkReviewResultDTO:
    """Xây dựng bản xem trước và áp dụng ngay lập tức trong 1 thao tác cho đề xuất EDC."""
    preview = build_preview_for_scope(
        project,
        kind,
        proposal_ids,
        batch_action=batch_action,
        shared_note=shared_note,
        client=client,
        state_store=state_store,
    )
    if not preview.can_apply_all and not preview.can_apply_valid_only:
        err_msg = "; ".join(preview.batch_errors) if preview.batch_errors else "Không có mục hợp lệ để áp dụng."
        raise ValueError(err_msg)
    apply_mode = "all_or_nothing" if preview.can_apply_all else "valid_only"
    return execute_batch_apply(project, kind, apply_mode=apply_mode, client=client, state_store=state_store)
