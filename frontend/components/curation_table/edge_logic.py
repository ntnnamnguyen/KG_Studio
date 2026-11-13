"""Logic lọc, sắp xếp, dựng dòng và xử lý lô quyết định cho bảng quan hệ (Trang 4)."""
from __future__ import annotations

import json
from typing import Any

from backend.domain.catalogs.service import compute_project_revision
from backend.domain.curation.service import (
    build_curation_validation_context,
    evidence_context,
    find_document,
    inspect_edge_schema_status,
)
from backend.facade import get_facade
from frontend.client import FrontendClient
from frontend.state.session import (
    get_curation_section_state,
    reconcile_edge_state_after_apply,
    store_curation_edge_preview,
)
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.schemas.curation import (
    CurationPreviewDTO,
    CurationResultDTO,
    CurationReviewRequestDTO,
    EdgeReviewDecisionDTO,
)
from shared.text_utils import normal, sha, uid


def compute_edge_filter_signature(filters: dict[str, Any]) -> str:
    """Tính chữ ký xác định cho bộ lọc bảng quan hệ."""
    payload = {
        "status": filters.get("status", "all"),
        "doc_id": filters.get("doc_id", "all"),
        "relation": filters.get("relation", "all"),
        "entity_id": filters.get("entity_id", "all"),
        "entity_kind": filters.get("entity_kind", "all"),
        "evidence_state": filters.get("evidence_state", "all"),
        "schema_state": filters.get("schema_state", "all"),
        "search": str(filters.get("search") or "").strip(),
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def _edge_priority_rank(
    project: dict,
    edge: dict,
    *,
    precomputed: dict[str, Any] | None = None,
    ev_ctx: dict[str, Any] | None = None,
    schema_info: dict[str, Any] | None = None,
) -> tuple[int, int, str]:
    """Xếp hạng độ ưu tiên kiểm duyệt của cạnh (Cần kiểm tra -> Chờ duyệt -> Đã duyệt -> Loại bỏ)."""
    status = str(edge.get("status", STATUS_PENDING))
    status_order = {
        STATUS_CHECK: 0,
        STATUS_PENDING: 1,
        STATUS_APPROVED: 2,
        STATUS_REJECTED: 3,
    }.get(status, 4)
    if ev_ctx is None:
        ev_ctx = evidence_context(project, edge, precomputed=precomputed, include_snippets=False)
    if schema_info is None:
        schema_info = inspect_edge_schema_status(project, edge, precomputed=precomputed)
    issue_rank = 0
    if not ev_ctx.get("found"):
        issue_rank -= 2
    if schema_info.get("status_code") != "valid":
        issue_rank -= 1
    return (status_order, issue_rank, str(edge.get("id", "")))


def filter_and_sort_edges(project: dict, filters: dict[str, Any]) -> list[dict]:
    """Lọc và sắp xếp danh sách cạnh theo bộ lọc Khu vực A."""
    f_status = str(filters.get("status") or "all")
    f_doc = str(filters.get("doc_id") or "all")
    f_rel = str(filters.get("relation") or "all")
    f_rel_norm = normal(f_rel) if f_rel != "all" else ""
    f_ent = str(filters.get("entity_id") or "all")
    f_kind = str(filters.get("entity_kind") or "all")
    f_kind_norm = normal(f_kind) if f_kind != "all" else ""
    f_ev = str(filters.get("evidence_state") or "all")
    f_schema = str(filters.get("schema_state") or "all")
    f_search = normal(str(filters.get("search") or ""))
    sort_by = str(filters.get("sort_by") or "priority")
    sort_desc = bool(filters.get("sort_desc", False))

    needs_priority_sort = sort_by not in ("relation", "source", "status")
    needs_val_ctx = (f_ev not in ("all", "override")) or (f_schema != "all") or needs_priority_sort
    val_ctx = build_curation_validation_context(project) if needs_val_ctx else None
    nodes_by_id = val_ctx["nodes"] if val_ctx is not None else {str(n.get("id", "")): n for n in project.get("nodes", [])}

    matched: list[dict] = []
    priority_ranks: dict[int, tuple[int, int, str]] = {}

    for edge in project.get("edges", []):
        if f_status != "all" and edge.get("status") != f_status:
            continue
        if f_doc != "all" and edge.get("doc_id") != f_doc:
            continue
        if f_rel != "all" and normal(edge.get("relation", "")) != f_rel_norm:
            continue
        src_id = str(edge.get("source", ""))
        tgt_id = str(edge.get("target", ""))
        if f_ent != "all" and f_ent not in (src_id, tgt_id):
            continue

        src_node = nodes_by_id.get(src_id, {})
        tgt_node = nodes_by_id.get(tgt_id, {})
        if f_kind != "all":
            if normal(src_node.get("kind", "")) != f_kind_norm and normal(tgt_node.get("kind", "")) != f_kind_norm:
                continue

        if f_ev == "override" and not edge.get("override"):
            continue

        if f_search:
            haystack = " ".join(
                [
                    str(src_node.get("name", "")),
                    str(tgt_node.get("name", "")),
                    str(edge.get("relation", "")),
                    str(edge.get("evidence", "")),
                    str(edge.get("review_note", "")),
                ]
            )
            if f_search not in normal(haystack):
                continue

        schema_info: dict[str, Any] | None = None
        if f_schema != "all":
            schema_info = inspect_edge_schema_status(project, edge, precomputed=val_ctx)
            if f_schema == "valid" and schema_info["status_code"] != "valid":
                continue
            if f_schema == "blocked" and schema_info["status_code"] == "valid":
                continue
            if f_schema in ("pending_proposal", "rejected_proposal", "out_of_catalog") and schema_info["status_code"] != f_schema:
                continue

        ev_ctx: dict[str, Any] | None = None
        if f_ev not in ("all", "override"):
            ev_ctx = evidence_context(project, edge, precomputed=val_ctx, include_snippets=False)
            if f_ev == "matched" and not ev_ctx.get("found"):
                continue
            if f_ev == "not_found" and (ev_ctx.get("found") or edge.get("override")):
                continue
            if f_ev == "ambiguous" and not ev_ctx.get("ambiguous"):
                continue

        if needs_priority_sort:
            priority_ranks[id(edge)] = _edge_priority_rank(
                project,
                edge,
                precomputed=val_ctx,
                ev_ctx=ev_ctx,
                schema_info=schema_info,
            )

        matched.append(edge)

    if sort_by == "relation":
        matched.sort(key=lambda e: (normal(e.get("relation", "")), str(e.get("id", ""))), reverse=sort_desc)
    elif sort_by == "source":
        matched.sort(
            key=lambda e: (normal(nodes_by_id.get(str(e.get("source", "")), {}).get("name", "")), str(e.get("id", ""))),
            reverse=sort_desc,
        )
    elif sort_by == "status":
        matched.sort(key=lambda e: (str(e.get("status", "")), str(e.get("id", ""))), reverse=sort_desc)
    else:
        matched.sort(key=lambda e: priority_ranks[id(e)], reverse=sort_desc)

    return matched


def format_edge_source_badge(
    project: dict,
    edge: dict,
    *,
    docs_by_id: dict[str, dict] | None = None,
) -> str:
    """Hiển thị nguồn (doc_name, chunk_number, và chỉ hiện số trang khi tài liệu thật sự có thông tin trang)."""
    doc_id = str(edge.get("doc_id", ""))
    doc = docs_by_id.get(doc_id) if docs_by_id is not None else find_document(project, doc_id)
    doc_name = str((doc or {}).get("name") or edge.get("doc_name") or edge.get("doc_id") or "Không rõ")
    parts = [doc_name]
    if edge.get("chunk_number") is not None:
        parts.append(f"Đoạn {edge['chunk_number']}")
    if doc and doc.get("pages") and edge.get("page") is not None:
        parts.append(f"Trang {edge['page']}")
    return " · ".join(parts)


def build_edge_table_rows(
    project: dict,
    edges: list[dict],
    selected_ids: list[str] | set[str],
) -> list[dict[str, Any]]:
    """Tạo dữ liệu hiển thị cho bảng quan hệ đúng theo mục 5.1."""
    if not edges:
        return []
    val_ctx = build_curation_validation_context(project)
    nodes_by_id = val_ctx["nodes"]
    docs_by_id = val_ctx["docs_by_id"]
    sel_set = set(selected_ids)
    rows: list[dict[str, Any]] = []
    for edge in edges:
        eid = str(edge.get("id", ""))
        src = nodes_by_id.get(str(edge.get("source", "")), {})
        tgt = nodes_by_id.get(str(edge.get("target", "")), {})
        ev_ctx = evidence_context(project, edge, precomputed=val_ctx, include_snippets=False)
        schema_info = inspect_edge_schema_status(project, edge, precomputed=val_ctx)
        quote = str(edge.get("evidence") or "").strip()
        short_quote = quote if len(quote) <= 90 else f"{quote[:87]}..."
        rows.append(
            {
                "edge_id": eid,
                "selected": eid in sel_set,
                "eligible_for_batch": edge.get("status") in (STATUS_PENDING, STATUS_CHECK),
                "source_display": f"{src.get('name', edge.get('source', ''))} [{src.get('kind', '?')}]",
                "relation_display": str(edge.get("relation", "")).strip(),
                "target_display": f"{tgt.get('name', edge.get('target', ''))} [{tgt.get('kind', '?')}]",
                "evidence_snippet": short_quote,
                "source_location": format_edge_source_badge(project, edge, docs_by_id=docs_by_id),
                "evidence_match_label": ev_ctx.get("match_label", ""),
                "schema_badge": schema_info.get("badge_label", schema_info.get("label", "")),
                "schema_status_label": schema_info["label"],
                "schema_status_code": schema_info["status_code"],
                "schema_issue": schema_info.get("issue", ""),
                "blocking_proposal_ids": schema_info["blocking_proposal_ids"],
                "status": str(edge.get("status", STATUS_PENDING)),
            }
        )
    return rows


def build_edge_batch_preview(
    project: dict,
    edge_ids: list[str],
    action: str,
    *,
    reason_code: str = "",
    note: str = "",
    allow_schema_bypass: bool = False,
    auto_sync_catalog: bool = True,
    filter_summary: dict[str, Any] | None = None,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> CurationPreviewDTO:
    """Đóng gói các cạnh được chọn theo ID và gọi Backend tạo bản xem trước lô duyệt cạnh."""
    svc_client = client or get_facade()
    locked_ids = list(dict.fromkeys(str(eid).strip() for eid in edge_ids if str(eid).strip()))
    decisions = [
        EdgeReviewDecisionDTO(
            edge_id=eid,
            action=action,
            reason_code=reason_code if action in ("reject", STATUS_REJECTED) else "",
            note=note,
        )
        for eid in locked_ids
    ]
    req_id = uid()
    req = CurationReviewRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        decisions=decisions,
        apply_mode="all_or_nothing",
        is_batch=True,
        allow_schema_bypass=allow_schema_bypass,
        auto_sync_catalog=auto_sync_catalog,
        expected_revision=compute_project_revision(project),
        request_id=req_id,
        filter_summary=dict(filter_summary or {}),
    )
    preview = svc_client.preview_curation_decisions(project, req)
    store_curation_edge_preview(
        project,
        preview,
        decisions,
        request_id=req_id,
        allow_schema_bypass=allow_schema_bypass,
        auto_sync_catalog=auto_sync_catalog,
        state_store=state_store,
    )
    return preview


def execute_edge_batch_apply(
    project: dict,
    *,
    apply_mode: str = "all_or_nothing",
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> CurationResultDTO:
    """Thực thi lô duyệt cạnh đã xem trước và đồng bộ lại lựa chọn theo kết quả."""
    svc_client = client or get_facade()
    s_state = get_curation_section_state(project, "edges", state_store)
    active_prev = s_state.get("active_preview")
    raw_decisions = s_state.get("preview_decisions") or []
    if not active_prev or not raw_decisions:
        raise ValueError("Cần chạy Xem trước lô quyết định trước khi áp dụng.")

    decisions = [EdgeReviewDecisionDTO.from_dict(d) for d in raw_decisions]
    allow_schema_bypass = bool(s_state.get("preview_allow_schema_bypass", False))
    auto_sync_catalog = bool(s_state.get("preview_auto_sync_catalog", True))
    req = CurationReviewRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        decisions=decisions,
        apply_mode=apply_mode,
        is_batch=True,
        allow_schema_bypass=allow_schema_bypass,
        auto_sync_catalog=auto_sync_catalog,
        expected_revision=str(active_prev.get("revision") or compute_project_revision(project)),
        request_id=str(s_state.get("preview_request_id") or uid()),
        filter_summary=dict(active_prev.get("filter_summary") or {}),
    )
    result = svc_client.apply_curation_decisions(project, req, preview=active_prev)
    reconcile_edge_state_after_apply(project, result, state_store=state_store)
    return result


def quick_apply_edge_batch(
    project: dict,
    edge_ids: list[str],
    action: str,
    *,
    reason_code: str = "",
    note: str = "",
    apply_mode: str = "valid_only",
    allow_schema_bypass: bool = False,
    auto_sync_catalog: bool = True,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> CurationResultDTO:
    """Xây dựng bản xem trước và áp dụng ngay lập tức trong 1 thao tác cho danh sách cạnh được chọn."""
    preview = build_edge_batch_preview(
        project,
        edge_ids,
        action,
        reason_code=reason_code,
        note=note,
        allow_schema_bypass=allow_schema_bypass,
        auto_sync_catalog=auto_sync_catalog,
        client=client,
        state_store=state_store,
    )
    if preview.invalid_count > 0 and apply_mode == "all_or_nothing":
        raise ValueError(f"Có {preview.invalid_count} cạnh không hợp lệ, không thể áp dụng theo chế độ all_or_nothing.")
    if preview.valid_count == 0:
        if preview.excluded_processed_count == len(preview.locked_edge_ids) and preview.excluded_processed_count > 0:
            rev = compute_project_revision(project)
            return CurationResultDTO(
                batch_id=preview.preview_id,
                request_id=preview.preview_id,
                project_id=str(project.get("project_id") or project.get("name") or ""),
                operation=f"batch_{action}",
                status="no_op",
                applied_count=0,
                skipped_count=preview.excluded_processed_count,
                applied_ids=[],
                skipped_ids=list(preview.locked_edge_ids),
                revision_before=rev,
                revision_after=rev,
            )
        if action == "approve":
            unique_reasons: list[str] = []
            for it in preview.item_previews:
                for err in it.get("errors", []):
                    if err not in unique_reasons:
                        unique_reasons.append(err)
            err_detail = "; ".join(unique_reasons[:3]) if unique_reasons else ""
            if preview.excluded_processed_count > 0 and err_detail:
                err_msg = f"Không có cạnh mới nào đủ điều kiện để duyệt ({preview.excluded_processed_count} cạnh đã ở trạng thái Đã duyệt từ trước; các cạnh còn lại bị chặn: {err_detail})."
            elif err_detail:
                err_msg = f"Không có cạnh nào đủ điều kiện hợp lệ để duyệt (Chi tiết: {err_detail})."
            else:
                err_msg = "; ".join(preview.batch_errors) if preview.batch_errors else "Không có cạnh nào đủ điều kiện hợp lệ để duyệt."
            raise ValueError(err_msg)
    eff_mode = "all_or_nothing" if preview.can_apply_all else "valid_only"
    return execute_edge_batch_apply(project, apply_mode=eff_mode, client=client, state_store=state_store)
