"""Bảng kiểm duyệt quan hệ, thanh duyệt hàng loạt và bảng danh sách thực thể (Trang 5)."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows, compute_project_revision
from backend.domain.curation.service import (
    build_curation_validation_context,
    duplicate_suggestions,
    evidence_context,
    find_document,
    find_node,
    inspect_edge_schema_status,
    node_degrees,
)
from backend.facade import get_facade
from frontend.components.shared_curation_ui import paginate_items, render_selection_action_bar
from frontend.client import FrontendClient
from frontend.state.session import (
    clear_edge_selection,
    clear_entity_selection,
    filter_edges_by_entity,
    get_curation_section_state,
    reconcile_edge_selection_with_filter,
    reconcile_edge_state_after_apply,
    reconcile_entity_selection_with_filter,
    select_all_filtered_edges,
    select_all_filtered_entities,
    select_page_edges,
    select_page_entities,
    set_active_curation_section,
    set_focused_edge,
    set_focused_entity,
    stage_entities_for_merge,
    store_curation_edge_preview,
    toggle_edge_selection,
    toggle_entity_selection,
)
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.schemas.curation import (
    REJECTION_REASON_CODES,
    CurationPreviewDTO,
    CurationResultDTO,
    CurationReviewRequestDTO,
    EdgeReviewDecisionDTO,
)
from shared.text_utils import normal, sha, uid


def compute_edge_filter_signature(filters: dict[str, Any]) -> str:
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


# paginate_items được import dùng chung từ frontend.components.shared_curation_ui


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


def filter_and_sort_entities(
    project: dict,
    filters: dict[str, Any],
    *,
    dup_node_ids: set[str] | None = None,
) -> list[dict]:
    """Lọc và sắp xếp danh sách thực thể cho Khu vực B (mục 6.1)."""
    degrees = node_degrees(project)
    proposals = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    type_norms = {normal(t["name"]) for t in project.get("entity_types", []) if t.get("name")}
    f_kind = str(filters.get("kind") or "all")
    f_doc = str(filters.get("doc_id") or "all")
    f_schema = str(filters.get("schema_state") or "all")
    f_deg = str(filters.get("degree_filter") or "all")
    f_dup = bool(filters.get("dup_candidate_only", False))
    f_search = normal(str(filters.get("search") or ""))

    if dup_node_ids is None:
        if f_dup:
            sugs = duplicate_suggestions(project, fuzzy_threshold=0.82)
            dup_node_ids = {str(x) for s in sugs for x in (s.get("keep_id", s.get("node_a", {}).get("id")), s.get("drop_id", s.get("node_b", {}).get("id")))}
        else:
            dup_node_ids = set()

    matched: list[dict] = []
    for node in project.get("nodes", []):
        nid = str(node.get("id", ""))
        if f_kind != "all" and normal(node.get("kind", "")) != normal(f_kind):
            continue
        if f_doc != "all" and f_doc not in node.get("documents", []):
            continue
        if f_dup and nid not in dup_node_ids:
            continue

        deg_total = degrees.get(nid, {"total": 0})["total"]
        if f_deg == "isolated" and deg_total != 0:
            continue
        if f_deg == "gte_1" and deg_total < 1:
            continue
        if f_deg == "gte_3" and deg_total < 3:
            continue

        has_pending_prop = any(
            proposals.get(str(pid), {}).get("status") == "pending"
            for pid in node.get("schema_proposal_ids", [])
        )
        in_catalog = normal(node.get("kind", "")) in type_norms
        if f_schema == "valid" and (has_pending_prop or not in_catalog):
            continue
        if f_schema == "blocked" and not has_pending_prop and in_catalog:
            continue

        if f_search:
            hay = " ".join(
                [
                    str(node.get("name", "")),
                    str(node.get("kind", "")),
                    str(node.get("description", "")),
                    " ".join(str(a) for a in node.get("aliases", [])),
                ]
            )
            if f_search not in normal(hay):
                continue

        matched.append(node)

    sort_by = str(filters.get("sort_by") or "degree_desc")
    if sort_by == "name":
        matched.sort(key=lambda n: (normal(n.get("name", "")), str(n.get("id", ""))))
    elif sort_by == "kind":
        matched.sort(key=lambda n: (normal(n.get("kind", "")), normal(n.get("name", ""))))
    else:
        matched.sort(
            key=lambda n: (-degrees.get(str(n.get("id", "")), {"total": 0})["total"], normal(n.get("name", "")))
        )
    return matched


def build_entity_table_rows(project: dict, nodes: list[dict]) -> list[dict[str, Any]]:
    degrees = node_degrees(project)
    proposals = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    type_norms = {normal(t["name"]) for t in project.get("entity_types", []) if t.get("name")}
    rows: list[dict[str, Any]] = []
    for node in nodes:
        nid = str(node.get("id", ""))
        deg = degrees.get(nid, {"in": 0, "out": 0, "total": 0})
        pending_pids = [
            str(pid)
            for pid in node.get("schema_proposal_ids", [])
            if proposals.get(str(pid), {}).get("status") == "pending"
        ]
        if pending_pids:
            schema_label = "Còn đề xuất chờ"
        elif normal(node.get("kind", "")) in type_norms:
            schema_label = "Đã chuẩn hóa"
        else:
            schema_label = "Ngoài danh mục"
        desc = str(node.get("description") or "").strip()
        rows.append(
            {
                "node_id": nid,
                "name": str(node.get("name", "")),
                "kind": str(node.get("kind", "")),
                "aliases_display": "; ".join(node.get("aliases", [])),
                "description_snippet": desc if len(desc) <= 80 else f"{desc[:77]}...",
                "doc_count": len(node.get("documents", [])),
                "degree_display": f"{deg['total']} (Vào: {deg['in']} · Ra: {deg['out']})",
                "degree_total": deg["total"],
                "schema_label": schema_label,
                "pending_proposal_ids": pending_pids,
            }
        )
    return rows


def render_edge_curation_table_and_batch_bar(project: dict) -> dict[str, Any]:
    """Hiển thị bộ lọc, bảng dữ kiện, thanh chọn theo ID và thanh Xem trước / Áp dụng lô."""
    s_state = get_curation_section_state(project, "edges")
    filters = s_state["filters"]
    docs = project.get("documents", [])
    doc_options = ["all"] + [str(d["id"]) for d in docs]
    doc_names = {"all": "Tất cả tài liệu", **{str(d["id"]): str(d.get("name", d["id"])) for d in docs}}

    nodes = project.get("nodes", [])
    node_options = ["all"] + [str(n["id"]) for n in nodes]
    node_names = {"all": "Tất cả thực thể", **{str(n["id"]): f"{n.get('name', '')} [{n.get('kind', '')}]" for n in nodes}}

    rel_options = ["all"] + sorted({str(e.get("relation", "")) for e in project.get("edges", []) if e.get("relation")})
    kind_options = ["all"] + sorted({str(n.get("kind", "")) for n in nodes if n.get("kind")})

    # 1. Tính toán số bộ lọc nâng cao đang bật để hiển thị badge số đếm
    adv_active_count = sum([
        filters.get("doc_id", "all") != "all",
        filters.get("relation", "all") != "all",
        filters.get("entity_id", "all") != "all",
        filters.get("entity_kind", "all") != "all",
        filters.get("evidence_state", "all") != "all",
        filters.get("schema_state", "all") != "all",
    ])
    adv_label = f"⚙️ Bộ lọc nâng cao ({adv_active_count})" if adv_active_count > 0 else "⚙️ Bộ lọc nâng cao"

    # TẦNG 1: THANH CƠ BẢN TINH GỌN (CHỈ 1 DÒNG DUY NHẤT)
    c_search, c_status = st.columns([3.5, 1.5])
    filters["search"] = c_search.text_input(
        "Tìm kiếm từ khóa",
        value=filters.get("search", ""),
        placeholder="🔍 Tìm nhanh thực thể, quan hệ, trích dẫn bằng chứng...",
        label_visibility="collapsed",
        key="cur_edge_f_search",
    )
    status_opts = ["all", STATUS_CHECK, STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED]
    filters["status"] = c_status.selectbox(
        "Trạng thái duyệt",
        status_opts,
        index=status_opts.index(filters["status"]) if filters["status"] in status_opts else 0,
        format_func=lambda x: "Tất cả trạng thái" if x == "all" else f"Trạng thái: {x}",
        label_visibility="collapsed",
        key="cur_edge_f_status",
    )

    # TẦNG 2: VÙNG MỞ RỘNG BỘ LỌC NÂNG CAO (Mặc định thu gọn, mở khi có tiêu chí đang lọc)
    with st.expander(adv_label, expanded=bool(adv_active_count > 0)):
        f1, f2, f3, f4 = st.columns(4)
        filters["doc_id"] = f1.selectbox(
            "Tài liệu nguồn",
            doc_options,
            index=doc_options.index(filters["doc_id"]) if filters["doc_id"] in doc_options else 0,
            format_func=lambda x: doc_names.get(x, x),
            key="cur_edge_f_doc",
        )
        filters["relation"] = f2.selectbox(
            "Loại quan hệ",
            rel_options,
            index=rel_options.index(filters["relation"]) if filters["relation"] in rel_options else 0,
            format_func=lambda x: "Tất cả quan hệ" if x == "all" else x,
            key="cur_edge_f_rel",
        )
        filters["entity_id"] = f3.selectbox(
            "Thực thể liên quan",
            node_options,
            index=node_options.index(filters["entity_id"]) if filters["entity_id"] in node_options else 0,
            format_func=lambda x: node_names.get(x, x),
            key="cur_edge_f_ent",
        )
        filters["entity_kind"] = f4.selectbox(
            "Loại thực thể đầu mút",
            kind_options,
            index=kind_options.index(filters["entity_kind"]) if filters["entity_kind"] in kind_options else 0,
            format_func=lambda x: "Tất cả loại" if x == "all" else x,
            key="cur_edge_f_kind",
        )

        f5, f6, f_reset = st.columns([2, 2, 1])
        ev_opts = ["all", "matched", "not_found", "override", "ambiguous"]
        ev_labels = {
            "all": "Mọi tình trạng bằng chứng",
            "matched": "Khớp tài liệu",
            "not_found": "Không tìm thấy trích dẫn",
            "override": "Ngoại lệ bằng chứng",
            "ambiguous": "Nhiều vị trí khớp",
        }
        filters["evidence_state"] = f5.selectbox(
            "Tình trạng bằng chứng",
            ev_opts,
            index=ev_opts.index(filters["evidence_state"]) if filters["evidence_state"] in ev_opts else 0,
            format_func=lambda x: ev_labels.get(x, x),
            key="cur_edge_f_ev",
        )
        sc_opts = ["all", "valid", "blocked", "pending_proposal", "rejected_proposal", "out_of_catalog"]
        sc_labels = {
            "all": "Mọi tình trạng danh mục",
            "valid": "Hợp lệ danh mục",
            "blocked": "Đang vướng danh mục",
            "pending_proposal": "Còn đề xuất EDC chờ",
            "rejected_proposal": "Đề xuất EDC bị từ chối",
            "out_of_catalog": "Ngoài danh mục",
        }
        filters["schema_state"] = f6.selectbox(
            "Tình trạng danh mục",
            sc_opts,
            index=sc_opts.index(filters["schema_state"]) if filters["schema_state"] in sc_opts else 0,
            format_func=lambda x: sc_labels.get(x, x),
            key="cur_edge_f_schema",
        )
        f_reset.write("")
        f_reset.write("")
        if f_reset.button("🔄 Đặt lại lọc", key="cur_edge_btn_reset_filters", help="Xóa nhanh toàn bộ bộ lọc nâng cao"):
            filters["doc_id"] = "all"
            filters["relation"] = "all"
            filters["entity_id"] = "all"
            filters["entity_kind"] = "all"
            filters["evidence_state"] = "all"
            filters["schema_state"] = "all"
            st.rerun()

    filtered_edges = filter_and_sort_edges(project, filters)
    filter_sig = compute_edge_filter_signature(filters)
    reconcile_edge_selection_with_filter(project, filter_sig, filtered_edges)

    if s_state.get("filter_prune_notice"):
        st.info(f"ℹ️ {s_state['filter_prune_notice']}")

    page_edges, cur_page, total_pages = paginate_items(
        filtered_edges,
        filters.get("page", 1),
        filters.get("page_size", 25),
    )
    filters["page"] = cur_page

    # Đảm bảo có một cạnh đang được mở xem chi tiết nhưng KHÔNG tự chọn checkbox
    if page_edges and (
        not s_state.get("focused_edge_id")
        or all(str(e["id"]) != s_state["focused_edge_id"] for e in filtered_edges)
    ):
        set_focused_edge(project, str(page_edges[0]["id"]))

    page_res = render_selection_action_bar(
        selected_count=len(s_state["selected_ids"]),
        page_eligible_count=len(page_edges),
        filtered_eligible_count=sum(1 for e in filtered_edges if e.get("status") in (STATUS_PENDING, STATUS_CHECK)),
        total_count=len(project.get("edges", [])),
        key_prefix="cur_edge",
        item_noun="cạnh",
        on_select_page=lambda: select_page_edges(project, page_edges),
        on_select_all_filtered=lambda: select_all_filtered_edges(project, filtered_edges),
        on_clear=lambda: clear_edge_selection(project),
        page_size=filters["page_size"],
        current_page=cur_page,
        total_pages=total_pages,
    )
    if page_res:
        filters["page"], filters["page_size"] = page_res

    display_rows = build_edge_table_rows(project, page_edges, s_state["selected_ids"])
    st.caption(
        f"Hiển thị **{len(page_edges)} / {len(filtered_edges)}** quan hệ khớp bộ lọc · "
        f"Đang chọn **{len(s_state['selected_ids'])}** quan hệ chờ xử lý."
    )

    if display_rows:
        table_rows = [
            {
                "id": r["edge_id"],
                "Chọn": bool(r["selected"]),
                "Thực thể nguồn": r["source_display"],
                "Quan hệ": r["relation_display"],
                "Thực thể đích": r["target_display"],
                "Tình trạng Lược đồ": r["schema_badge"],
                "Trích dẫn bằng chứng": r["evidence_snippet"],
                "Nguồn dẫn chứng": r["source_location"],
                "Khớp bằng chứng": r["evidence_match_label"],
                "Trạng thái": r["status"],
            }
            for r in display_rows
        ]
        edited_edge_rows = st.data_editor(
            table_rows,
            key=f"cur_edge_editor_{cur_page}_{filter_sig}",
            width='stretch',
            hide_index=True,
            disabled=[
                "id",
                "Thực thể nguồn",
                "Quan hệ",
                "Thực thể đích",
                "Tình trạng Lược đồ",
                "Trích dẫn bằng chứng",
                "Nguồn dẫn chứng",
                "Khớp bằng chứng",
                "Trạng thái",
            ],
            column_config={
                "id": None,
                "Chọn": st.column_config.CheckboxColumn("Chọn", default=False),
            },
        )
        page_changed_selection = False
        for erow in edited_edge_rows:
            eid = str(erow.get("id", ""))
            want_sel = bool(erow.get("Chọn", False))
            was_sel = eid in s_state["selected_ids"]
            if want_sel != was_sel:
                toggle_edge_selection(project, eid, want_sel)
                page_changed_selection = True
        if page_changed_selection:
            st.rerun()

        # Bộ điều khiển mở chi tiết 1 dòng để đối chiếu bằng chứng ở khung dưới
        ctrl1, ctrl2 = st.columns([3.0, 1.2])
        row_by_id = {r["edge_id"]: r for r in display_rows}
        edge_opts = [r["edge_id"] for r in display_rows]
        cur_focus = s_state.get("focused_edge_id")
        default_idx = edge_opts.index(cur_focus) if cur_focus in edge_opts else 0
        chosen_eid = ctrl1.selectbox(
            "🔎 Chọn dòng quan hệ để đối chiếu bằng chứng & sửa chi tiết ở khung dưới",
            edge_opts,
            index=default_idx,
            format_func=lambda eid: (
                f"[{row_by_id[eid]['status']}] {row_by_id[eid]['source_display']} → "
                f"{row_by_id[eid]['relation_display']} → {row_by_id[eid]['target_display']}"
            ),
            key="cur_focus_edge_select",
        )
        if chosen_eid != cur_focus:
            set_focused_edge(project, chosen_eid)
            st.rerun()
        ctrl2.caption(f"Đang xem chi tiết cạnh `{cur_focus or chosen_eid}`.")
    else:
        st.info("Không có quan hệ nào khớp bộ lọc hiện tại.")

    # Thanh thao tác hàng loạt
    sel_ids = list(s_state["selected_ids"])
    with st.container(border=True):
        st.markdown(f"##### ⚡ Thao tác Nhanh cho **{len(sel_ids)}** Quan hệ Đang Chọn")
        allow_bypass = st.checkbox(
            "🔓 Cho phép duyệt cả cạnh chưa hợp lệ Lược đồ / Bỏ qua lỗi danh mục (Tự động nạp vào Danh mục chính thức)",
            value=True,
            key="cur_batch_allow_bypass_schema",
            help="Khi bật: Duyệt thành công tất cả các cạnh được chọn kể cả khi quan hệ/loại thực thể đang chờ duyệt, ngoài danh mục hoặc từng bị từ chối; đồng thời tự động cập nhật đề xuất và nạp vào danh mục chính thức để đồ thị đạt chuẩn hợp lệ.",
        )
        qb1, qb2, qb3 = st.columns(3)
        if qb1.button(
            f"✅ Duyệt ngay {len(sel_ids)} cạnh đã chọn",
            disabled=len(sel_ids) == 0,
            type="primary" if len(sel_ids) > 0 else "secondary",
            width='stretch',
            key="btn_cur_quick_approve",
            help="Duyệt ngay tất cả các cạnh đang được chọn (khi bật tùy chọn trên, tự động nạp danh mục và bỏ qua chặn đề xuất)",
        ):
            try:
                res = quick_apply_edge_batch(
                    project,
                    sel_ids,
                    "approve",
                    apply_mode="valid_only",
                    allow_schema_bypass=allow_bypass,
                    auto_sync_catalog=True,
                )
                if res.status == "no_op":
                    st.info(f"ℹ️ Toàn bộ {res.skipped_count} cạnh đang chọn đều đã ở trạng thái Đã duyệt từ trước.")
                else:
                    msg = f"Đã duyệt thành công {res.applied_count} cạnh mới (Lô `{res.batch_id}`)."
                    if res.skipped_count > 0:
                        msg += f" Đã bỏ qua {res.skipped_count} cạnh đã duyệt từ trước hoặc không hợp lệ."
                    st.success(msg)
                    st.rerun()
            except Exception as exc:
                st.error(str(exc))

        if qb2.button(
            f"⚠️ Đánh dấu Cần kiểm tra ({len(sel_ids)})",
            disabled=len(sel_ids) == 0,
            width='stretch',
            key="btn_cur_quick_check",
            help="Chuyển toàn bộ các cạnh đã chọn sang trạng thái Cần kiểm tra",
        ):
            try:
                res = quick_apply_edge_batch(project, sel_ids, "check", apply_mode="valid_only")
                if res.status == "no_op":
                    st.info(f"ℹ️ Toàn bộ {res.skipped_count} cạnh đang chọn đều đã ở trạng thái Cần kiểm tra từ trước.")
                else:
                    st.success(f"Đã chuyển {res.applied_count} cạnh sang trạng thái Cần kiểm tra.")
                    st.rerun()
            except Exception as exc:
                st.error(str(exc))

        if qb3.button(
            f"⛔ Loại bỏ {len(sel_ids)} cạnh đã chọn",
            disabled=len(sel_ids) == 0,
            width='stretch',
            key="btn_cur_quick_reject",
            help="Loại bỏ toàn bộ các cạnh đang chọn",
        ):
            try:
                res = quick_apply_edge_batch(project, sel_ids, "reject", reason_code="incorrect_fact", note="Loại bỏ hàng loạt", apply_mode="valid_only")
                if res.status == "no_op":
                    st.info(f"ℹ️ Toàn bộ {res.skipped_count} cạnh đang chọn đều đã ở trạng thái Loại bỏ từ trước.")
                else:
                    st.success(f"Đã loại bỏ {res.applied_count} cạnh.")
                    st.rerun()
            except Exception as exc:
                st.error(str(exc))

        with st.expander("⚙️ Tùy chọn Lô nâng cao & Xem trước chi tiết (Preview)", expanded=False):
            b1, b2, b3, b4 = st.columns([1.3, 1.5, 1.8, 1.2])
            batch_action_labels = {
                "approve": "Duyệt các cạnh hợp lệ đã chọn",
                "check": "Đánh dấu Cần kiểm tra",
                "reject": "Loại bỏ các cạnh đã chọn",
            }
            b_action = b1.selectbox(
                "Hành động hàng loạt",
                list(batch_action_labels.keys()),
                format_func=lambda k: batch_action_labels[k],
                key="cur_batch_action_select",
            )
            b_reason = ""
            if b_action == "reject":
                reason_opts = list(REJECTION_REASON_CODES.keys())
                b_reason = b2.selectbox(
                    "Mã lý do loại bỏ",
                    reason_opts,
                    format_func=lambda k: REJECTION_REASON_CODES[k],
                    key="cur_batch_reject_reason",
                )
            else:
                b2.caption("Duyệt lô tự động loại trừ cạnh thiếu bằng chứng hoặc tự nối.")
            b_note = b3.text_input("Ghi chú lô kiểm duyệt", key="cur_batch_note")
            if b4.button(
                f"👁️ Xem trước lô ({len(sel_ids)})",
                disabled=len(sel_ids) == 0,
                width='stretch',
                key="btn_cur_preview_batch",
            ):
                build_edge_batch_preview(
                    project,
                    sel_ids,
                    b_action,
                    reason_code=b_reason,
                    note=b_note,
                    allow_schema_bypass=allow_bypass,
                    auto_sync_catalog=True,
                    filter_summary=dict(filters),
                )
                st.rerun()

            active_prev = s_state.get("active_preview")
            if isinstance(active_prev, dict):
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Tổng cạnh trong lô", active_prev.get("total_requested", 0))
                p2.metric("Hợp lệ để áp dụng", active_prev.get("valid_count", 0))
                p3.metric("Không hợp lệ / Bị chặn", active_prev.get("invalid_count", 0))
                p4.metric("Đã xử lý bị loại trừ", active_prev.get("excluded_processed_count", 0))

                invalid_rows = [it for it in active_prev.get("item_previews", []) if not it.get("valid")]
                if invalid_rows:
                    st.warning(f"Có {len(invalid_rows)} cạnh không đủ điều kiện trong lô:")
                    st.dataframe(
                        [
                            {
                                "ID cạnh": it.get("edge_id", ""),
                                "Nguồn": it.get("source_name", ""),
                                "Quan hệ": it.get("relation", ""),
                                "Đích": it.get("target_name", ""),
                                "Lý do chặn": "; ".join(it.get("errors", [])),
                            }
                            for it in invalid_rows
                        ],
                        width='stretch',
                        hide_index=True,
                    )

                ap1, ap2 = st.columns(2)
                if ap1.button(
                    "✅ Áp dụng toàn bộ lô (All-or-Nothing)",
                    disabled=not active_prev.get("can_apply_all", False),
                    width='stretch',
                    key="btn_cur_apply_all",
                ):
                    try:
                        res = execute_edge_batch_apply(project, apply_mode="all_or_nothing")
                        st.success(f"Đã áp dụng thành công {res.applied_count} cạnh (Lô `{res.batch_id}`).")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

                if ap2.button(
                    f"☑️ Chỉ áp dụng {active_prev.get('valid_count', 0)} mục hợp lệ (Giữ lại mục lỗi)",
                    disabled=not active_prev.get("can_apply_valid_only", False),
                    width='stretch',
                    key="btn_cur_apply_valid_only",
                ):
                    try:
                        res = execute_edge_batch_apply(project, apply_mode="valid_only")
                        st.success(
                            f"Đã áp dụng {res.applied_count} cạnh hợp lệ và giữ lại {res.skipped_count} cạnh lỗi để kiểm tra tiếp."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    return {
        "filtered_edges": filtered_edges,
        "page_edges": page_edges,
        "focused_edge_id": s_state.get("focused_edge_id", ""),
        "selected_ids": list(s_state["selected_ids"]),
    }


def render_entity_table(project: dict) -> dict[str, Any]:
    """Hiển thị bộ lọc và bảng danh sách thực thể ở Khu vực B (mục 6.1)."""
    e_state = get_curation_section_state(project, "entities")
    filters = e_state["filters"]
    docs = project.get("documents", [])
    doc_options = ["all"] + [str(d["id"]) for d in docs]
    doc_names = {"all": "Tất cả tài liệu", **{str(d["id"]): str(d.get("name", d["id"])) for d in docs}}
    kind_options = ["all"] + sorted({str(n.get("kind", "")) for n in project.get("nodes", []) if n.get("kind")})

    # Chỉ tính gợi ý trùng lặp khi người dùng thực sự kích hoạt bộ lọc nghi trùng
    dup_active = bool(filters.get("dup_candidate_only", False))
    if dup_active:
        sugs = duplicate_suggestions(project, fuzzy_threshold=0.82)
        dup_ids = {str(x) for s in sugs for x in (s.get("keep_id", s.get("node_a", {}).get("id")), s.get("drop_id", s.get("node_b", {}).get("id")))}
    else:
        dup_ids = set()

    # 1. Tính toán số bộ lọc nâng cao thực thể đang bật
    adv_ent_count = sum([
        filters.get("doc_id", "all") != "all",
        filters.get("degree_filter", "all") != "all",
        filters.get("schema_state", "all") != "all",
        bool(filters.get("dup_candidate_only", False)),
    ])
    adv_ent_label = f"⚙️ Bộ lọc nâng cao ({adv_ent_count})" if adv_ent_count > 0 else "⚙️ Bộ lọc nâng cao"

    # TẦNG 1: THANH CƠ BẢN TINH GỌN (CHỈ 1 DÒNG DUY NHẤT)
    c_ent_search, c_ent_kind = st.columns([3.5, 1.5])
    filters["search"] = c_ent_search.text_input(
        "Tìm thực thể",
        value=filters.get("search", ""),
        placeholder="🔍 Tìm tên thực thể, bí danh, mô tả...",
        label_visibility="collapsed",
        key="cur_ent_f_search",
    )
    filters["kind"] = c_ent_kind.selectbox(
        "Loại thực thể",
        kind_options,
        index=kind_options.index(filters["kind"]) if filters["kind"] in kind_options else 0,
        format_func=lambda x: "Tất cả loại" if x == "all" else f"Loại: {x}",
        label_visibility="collapsed",
        key="cur_ent_f_kind",
    )

    # TẦNG 2: VÙNG MỞ RỘNG BỘ LỌC NÂNG CAO (Mặc định thu gọn, mở khi có tiêu chí đang lọc)
    with st.expander(adv_ent_label, expanded=bool(adv_ent_count > 0)):
        c2, c3, c4 = st.columns([1.5, 1.2, 1.3])
        filters["doc_id"] = c2.selectbox(
            "Tài liệu nguồn",
            doc_options,
            index=doc_options.index(filters["doc_id"]) if filters["doc_id"] in doc_options else 0,
            format_func=lambda x: doc_names.get(x, x),
            key="cur_ent_f_doc",
        )
        deg_opts = ["all", "isolated", "gte_1", "gte_3"]
        deg_labels = {
            "all": "Mọi bậc kết nối",
            "isolated": "Cô lập (bậc = 0)",
            "gte_1": "Có kết nối (≥ 1)",
            "gte_3": "Nút trung tâm (≥ 3)",
        }
        filters["degree_filter"] = c3.selectbox(
            "Số kết nối",
            deg_opts,
            index=deg_opts.index(filters["degree_filter"]) if filters["degree_filter"] in deg_opts else 0,
            format_func=lambda x: deg_labels.get(x, x),
            key="cur_ent_f_deg",
        )
        sc_opts = ["all", "valid", "blocked"]
        sc_labels = {"all": "Mọi trạng thái danh mục", "valid": "Đã chuẩn hóa", "blocked": "Còn đề xuất chờ / Ngoài danh mục"}
        filters["schema_state"] = c4.selectbox(
            "Trạng thái danh mục",
            sc_opts,
            index=sc_opts.index(filters["schema_state"]) if filters["schema_state"] in sc_opts else 0,
            format_func=lambda x: sc_labels.get(x, x),
            key="cur_ent_f_schema",
        )

        c_chk, c_reset = st.columns([3.5, 1.5])
        filters["dup_candidate_only"] = c_chk.checkbox(
            f"Chỉ hiện thực thể đang nằm trong cặp nghi trùng" + (f" ({len(dup_ids)} thực thể)" if dup_active else " (bấm để quét)"),
            value=bool(filters.get("dup_candidate_only", False)),
            key="cur_ent_f_dup",
        )
        c_reset.write("")
        if c_reset.button("🔄 Đặt lại lọc", key="cur_ent_btn_reset_filters", help="Xóa nhanh toàn bộ bộ lọc nâng cao"):
            filters["doc_id"] = "all"
            filters["degree_filter"] = "all"
            filters["schema_state"] = "all"
            filters["dup_candidate_only"] = False
            st.rerun()

    filtered_nodes = filter_and_sort_entities(project, filters, dup_node_ids=dup_ids)
    ent_sig = f"{filters.get('kind')}_{filters.get('doc_id')}_{filters.get('schema_state')}_{filters.get('degree_filter')}_{filters.get('dup_candidate_only')}_{filters.get('search')}"
    reconcile_entity_selection_with_filter(project, ent_sig, filtered_nodes)

    page_nodes, cur_page, total_pages = paginate_items(filtered_nodes, filters.get("page", 1), filters.get("page_size", 25))
    filters["page"] = cur_page

    if page_nodes and (
        not e_state.get("focused_node_id")
        or all(str(n["id"]) != e_state["focused_node_id"] for n in filtered_nodes)
    ):
        set_focused_entity(project, str(page_nodes[0]["id"]))

    render_selection_action_bar(
        selected_count=len(e_state.get("selected_ids", [])),
        page_eligible_count=len(page_nodes),
        filtered_eligible_count=len(filtered_nodes),
        total_count=len(project.get("nodes", [])),
        key_prefix="cur_entity",
        item_noun="thực thể",
        on_select_page=lambda: select_page_entities(project, page_nodes),
        on_select_all_filtered=lambda: select_all_filtered_entities(project, filtered_nodes),
        on_clear=lambda: clear_entity_selection(project),
    )

    rows = build_entity_table_rows(project, page_nodes)
    selected_node_ids = set(e_state.get("selected_ids", []))
    st.caption(
        f"Hiển thị **{len(page_nodes)} / {len(filtered_nodes)}** thực thể khớp bộ lọc · "
        f"Đang chọn **{len(selected_node_ids)}** thực thể."
    )

    if rows:
        table_node_rows = [
            {
                "id": r["node_id"],
                "Chọn": r["node_id"] in selected_node_ids,
                "Tên thực thể": r["name"],
                "Loại thực thể": r["kind"],
                "Bí danh": r["aliases_display"],
                "Mô tả": r["description_snippet"],
                "Số tài liệu": r["doc_count"],
                "Bậc kết nối": r["degree_display"],
                "Trạng thái danh mục": r["schema_label"],
            }
            for r in rows
        ]
        edited_node_rows = st.data_editor(
            table_node_rows,
            key=f"cur_node_editor_{cur_page}_{ent_sig}",
            width='stretch',
            hide_index=True,
            disabled=[
                "id",
                "Tên thực thể",
                "Loại thực thể",
                "Bí danh",
                "Mô tả",
                "Số tài liệu",
                "Bậc kết nối",
                "Trạng thái danh mục",
            ],
            column_config={
                "id": None,
                "Chọn": st.column_config.CheckboxColumn("Chọn", default=False),
            },
        )
        node_sel_changed = False
        for nrow in edited_node_rows:
            nid = str(nrow.get("id", ""))
            want_sel = bool(nrow.get("Chọn", False))
            was_sel = nid in selected_node_ids
            if want_sel != was_sel:
                toggle_entity_selection(project, nid, want_sel)
                node_sel_changed = True
        if node_sel_changed:
            st.rerun()

        if selected_node_ids:
            with st.container(border=True):
                st.markdown(f"##### ⚡ Thao tác Hàng loạt cho **{len(selected_node_ids)}** Thực thể Đang Chọn")
                b_col1, b_col2, b_col3 = st.columns([2.0, 1.4, 1.4])
                approved_types = [str(t["name"]) for t in catalog_rows(project, "entity_types")]
                with b_col1:
                    bc1, bc2 = st.columns([1.5, 1.0])
                    batch_target_kind = bc1.selectbox(
                        "Loại thực thể đã duyệt để gán",
                        options=[""] + approved_types,
                        format_func=lambda x: "— Chọn loại thực thể —" if not x else x,
                        key="sel_batch_node_kind",
                    )
                    if bc2.button(
                        f"🏷️ Gán loại ({len(selected_node_ids)})",
                        disabled=not batch_target_kind,
                        width='stretch',
                        key="btn_apply_batch_node_kind",
                    ):
                        facade = get_facade()
                        facade.create_snapshot(project)
                        selected_set = set(selected_node_ids)
                        nodes_by_id = {str(n.get("id", "")): n for n in project.get("nodes", [])}
                        updated_cnt = 0
                        for nid in selected_node_ids:
                            node = nodes_by_id.get(str(nid))
                            if node:
                                node["kind"] = batch_target_kind
                                node["schema_proposal_ids"] = []
                                updated_cnt += 1
                        for edge in project.get("edges", []):
                            if edge.get("source") in selected_set or edge.get("target") in selected_set:
                                if edge.get("status") not in (STATUS_REJECTED, STATUS_APPROVED):
                                    edge["status"] = STATUS_CHECK
                        facade.save_project(project)
                        st.success(f"Đã gán loại '{batch_target_kind}' cho {updated_cnt} thực thể đã chọn.")
                        clear_entity_selection(project)
                        st.rerun()

                with b_col2:
                    if st.button(
                        f"🔀 Đưa {len(selected_node_ids)} thực thể vào Bàn gộp",
                        width='stretch',
                        key="btn_batch_stage_merge",
                    ):
                        stage_entities_for_merge(project, list(selected_node_ids), switch_to_merge=True)
                        st.rerun()

                with b_col3:
                    if st.button(
                        f"🔬 Lọc quan hệ của {len(selected_node_ids)} thực thể",
                        width='stretch',
                        key="btn_filter_edges_of_selected_nodes",
                    ):
                        set_active_curation_section(project, "edges")
                        e_edge_state = get_curation_section_state(project, "edges")
                        first_nid = next(iter(selected_node_ids))
                        e_edge_state["filters"]["entity_id"] = first_nid
                        st.session_state["curation_hub_active_tab"] = "edges"
                        st.rerun()

        act1, act2, act3 = st.columns([2.4, 1.2, 1.2])
        row_map = {r["node_id"]: r for r in rows}
        node_ids = [r["node_id"] for r in rows]
        cur_nid = e_state.get("focused_node_id")
        idx = node_ids.index(cur_nid) if cur_nid in node_ids else 0
        chosen_nid = act1.selectbox(
            "🔎 Chọn thực thể để sửa hồ sơ, xem quan hệ hoặc đưa vào bàn gộp",
            node_ids,
            index=idx,
            format_func=lambda nid: f"{row_map[nid]['name']} [{row_map[nid]['kind']}] — Kết nối: {row_map[nid]['degree_display']}",
            key="cur_focus_node_select",
        )
        if chosen_nid != cur_nid:
            set_focused_entity(project, chosen_nid)
            st.rerun()

        if act2.button("🔗 Xem quan hệ của thực thể này", width='stretch', key="btn_ent_view_edges"):
            filter_edges_by_entity(project, chosen_nid)
            st.rerun()

        if act3.button("➕ Đưa vào bàn gộp (Khu vực C)", width='stretch', key="btn_ent_stage_merge"):
            stage_entities_for_merge(project, [chosen_nid], switch_to_merge=True)
            st.rerun()
    else:
        st.info("Không có thực thể nào khớp bộ lọc hiện tại.")

    return {
        "filtered_nodes": filtered_nodes,
        "page_nodes": page_nodes,
        "focused_node_id": e_state.get("focused_node_id", ""),
    }

