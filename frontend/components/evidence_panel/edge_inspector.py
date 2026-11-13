"""Khung đối chiếu dữ kiện & bằng chứng hai cột, duyệt đơn và sửa dữ kiện cho một cạnh (Trang 4)."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows, compute_project_revision
from backend.domain.curation.service import (
    evidence_context,
    find_document,
    find_edge,
    inspect_edge_schema_status,
    validate_edge_for_approval,
)
from frontend.client import get_client
from frontend.state.session import (
    get_curation_section_state,
    navigate_to_edc_proposal_from_curation,
    set_focused_edge,
)
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.schemas.curation import (
    REJECTION_REASON_CODES,
    CurationReviewRequestDTO,
    EdgeEditRequestDTO,
    EdgeReviewDecisionDTO,
)
from shared.text_utils import uid
from .html_format import format_highlighted_evidence_html


def _render_edge_nav_header(project: dict, edge: dict) -> None:
    """Hiển thị thanh điều hướng Mục trước / Mục tiếp theo edge_id."""
    s_state = get_curation_section_state(project, "edges")
    project_edge_ids = {str(e["id"]) for e in project.get("edges", []) if e.get("id")}
    ordered_ids = [
        str(eid) for eid in (s_state.get("ordered_edge_ids") or [])
        if str(eid) in project_edge_ids
    ]
    if not ordered_ids:
        ordered_ids = [str(e["id"]) for e in project.get("edges", []) if e.get("id")]

    cur_pos = ordered_ids.index(str(edge["id"])) if str(edge["id"]) in ordered_ids else -1
    nav_title, nav_prev, nav_pos, nav_next = st.columns([3.0, 0.9, 1.0, 0.9])
    nav_title.markdown(f"#### 🔬 Đối chiếu Dữ kiện & Bằng chứng (`{edge['id']}`)")
    if nav_prev.button(
        "◀️ Mục trước",
        disabled=(cur_pos <= 0),
        width="stretch",
        key=f"btn_prev_focused_edge_{edge['id']}",
    ):
        set_focused_edge(project, ordered_ids[cur_pos - 1])
        st.rerun()
    if cur_pos >= 0:
        nav_pos.caption(f"Mục **{cur_pos + 1} / {len(ordered_ids)}**")
    if nav_next.button(
        "Mục tiếp ▶️",
        disabled=(cur_pos < 0 or cur_pos >= len(ordered_ids) - 1),
        width="stretch",
        key=f"btn_next_focused_edge_{edge['id']}",
    ):
        set_focused_edge(project, ordered_ids[cur_pos + 1])
        st.rerun()


def _render_proposed_fact_card(
    project: dict,
    edge: dict,
    src_node: dict,
    tgt_node: dict,
    schema_info: dict[str, Any],
) -> None:
    """Hiển thị Cột trái — Dữ kiện được đề xuất & liên kết tháo gỡ chặn danh mục."""
    with st.container(border=True):
        st.markdown("##### 📌 Cột trái — Dữ kiện được đề xuất")
        st.markdown(
            f"- **Thực thể nguồn:** `{src_node.get('name', edge.get('source', ''))}` "
            f"*(Loại: `{src_node.get('kind', '?')}`)*\n"
            f"- **Quan hệ chuẩn hiện tại:** `{edge.get('relation', '')}`\n"
            f"- **Thực thể đích:** `{tgt_node.get('name', edge.get('target', ''))}` "
            f"*(Loại: `{tgt_node.get('kind', '?')}`)*\n"
            f"- **Trạng thái kiểm duyệt:** **{edge.get('status', STATUS_PENDING)}**\n"
            f"- **Tình trạng danh mục:** **{schema_info.get('badge_label', schema_info['label'])}**"
        )
        if edge.get("edc_original"):
            orig = edge["edc_original"]
            st.caption(
                f"Nhãn mở EDC ban đầu: `{orig.get('relation', '')}` — "
                f"Định nghĩa ngữ cảnh: *{orig.get('relation_definition', '')}*"
            )
        if edge.get("model") or edge.get("run_id"):
            st.caption(f"Model trích xuất: `{edge.get('model', 'Không rõ')}` · Run: `{edge.get('run_id', '-')}`")

        # Nếu bị chặn bởi đề xuất EDC ở Trang 4 -> hiển thị nút liên kết trực tiếp sang tab Lược đồ
        blocking_pids = schema_info.get("blocking_proposal_ids", [])
        if schema_info["status_code"] != "valid":
            st.warning(f"⚠️ **Chặn duyệt theo danh mục:** {schema_info['issue']}")
            if blocking_pids:
                proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
                for pid in blocking_pids:
                    prop = proposals_by_id.get(str(pid), {})
                    p_label = f"{prop.get('name', pid)} ({prop.get('kind', '')} · {prop.get('status', 'pending')})"
                    if st.button(
                        f"🔗 Mở đề xuất `{p_label}` ở Trang 4 để xử lý",
                        key=f"btn_jump_p04_from_edge_{edge['id']}_{pid}",
                        width='stretch',
                    ):
                        navigate_to_edc_proposal_from_curation(
                            project,
                            str(pid),
                            edge_id=str(edge["id"]),
                            section="edges",
                        )
                        st.rerun()


def _render_source_context_card(
    project: dict,
    client: Any,
    edge: dict,
    ev_ctx: dict[str, Any],
) -> None:
    """Hiển thị Cột phải — Ngữ cảnh văn bản gốc, gợi ý tầng 2 và khóa vị trí span."""
    with st.container(border=True):
        st.markdown("##### 📄 Cột phải — Ngữ cảnh văn bản gốc")
        doc = find_document(project, str(edge.get("doc_id", "")))
        meta_parts = [f"Tài liệu: **{ev_ctx.get('doc_name') or edge.get('doc_name') or 'Không rõ'}**"]
        if edge.get("chunk_number") is not None:
            meta_parts.append(f"Đoạn: **{edge['chunk_number']}**")
        if doc and doc.get("pages") and ev_ctx.get("page") is not None:
            meta_parts.append(f"Trang: **{ev_ctx['page']}**")
        if ev_ctx.get("start_char") is not None and ev_ctx.get("end_char") is not None:
            meta_parts.append(f"Vị trí ký tự: `[{ev_ctx['start_char']}:{ev_ctx['end_char']}]`")
        meta_parts.append(f"Đối chiếu: **{ev_ctx.get('match_label', '')}**")
        st.caption(" · ".join(meta_parts))

        st.markdown(format_highlighted_evidence_html(ev_ctx), unsafe_allow_html=True)

        # Tầng 2 (Gợi ý khi Tầng 1 không tìm thấy): hiển thị top 1-2 đoạn gần nhất theo Lexical Cosine
        suggestions = ev_ctx.get("suggestions") or []
        if not ev_ctx.get("found") and suggestions:
            st.caption("💡 **Gợi ý đoạn văn bản gốc gần nhất (Lexical Cosine từ vựng — chỉ tham khảo, không tự duyệt):**")
            for sug in suggestions:
                page_txt = f" · Trang {sug['page']}" if sug.get("page") is not None else ""
                with st.container(border=True):
                    sc_left, sc_right = st.columns([2.6, 1.1])
                    sc_left.caption(
                        f"Gợi ý #{sug['rank']} · Độ khớp từ vựng: **{sug['score_pct']}%** · "
                        f"Vị trí `[{sug['start_char']}:{sug['end_char']}]`{page_txt}"
                    )
                    sc_left.markdown(f"> {html.escape(str(sug['text']))}")
                    if sc_right.button(
                        "✅ Dùng đoạn này làm bằng chứng",
                        width="stretch",
                        key=f"btn_apply_ev_sug_{edge['id']}_{sug['rank']}",
                    ):
                        try:
                            edit_req = EdgeEditRequestDTO(
                                project_id=str(project.get("project_id") or project.get("name") or ""),
                                edge_id=str(edge["id"]),
                                source=str(edge.get("source") or ""),
                                target=str(edge.get("target") or ""),
                                relation=str(edge.get("relation") or ""),
                                evidence=str(sug["text"]),
                                doc_id=str(edge.get("doc_id") or ""),
                                note=f"Cập nhật bằng chứng theo gợi ý #{sug['rank']} ({sug['score_pct']}%)",
                                expected_revision=compute_project_revision(project),
                                request_id=uid(),
                            )
                            client.edit_edge_fact(project, edit_req)
                            st.session_state.pop(f"edit_edge_ev_{edge['id']}", None)
                            st.success("Đã cập nhật câu bằng chứng nguyên văn và đối chiếu lại.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

        # Nếu có nhiều vị trí xuất hiện trong tài liệu -> cho phép chọn đúng vị trí xác minh
        candidates = ev_ctx.get("candidates") or []
        if len(candidates) > 1:
            st.info(
                f"🔎 Câu trích dẫn xuất hiện tại **{len(candidates)} vị trí** trong tài liệu. "
                "Hãy chọn đúng vị trí ngữ cảnh để khóa vị trí ký tự xác minh:"
            )
            cand_indices = list(range(len(candidates)))
            sc1, sc2 = st.columns([2.5, 1.1])
            chosen_c_idx = sc1.selectbox(
                "Vị trí xuất hiện trong tài liệu",
                cand_indices,
                format_func=lambda i: (
                    f"Vị trí #{candidates[i]['index']} [{candidates[i]['start_char']}:{candidates[i]['end_char']}]"
                    + (f" (Trang {candidates[i]['page']})" if candidates[i].get("page") is not None else "")
                    + f" — ...{candidates[i]['snippet'][:70]}..."
                ),
                key=f"sel_span_cand_{edge['id']}",
            )
            if sc2.button("📌 Khóa vị trí bằng chứng này", width='stretch', key=f"btn_lock_span_{edge['id']}"):
                cand = candidates[chosen_c_idx]
                client.select_evidence_span(project, edge["id"], cand["start_char"], cand["end_char"])
                st.success(f"Đã khóa vị trí bằng chứng [{cand['start_char']}:{cand['end_char']}].")
                st.rerun()


def _render_single_edge_decision_card(
    project: dict,
    client: Any,
    edge: dict,
    ev_ctx: dict[str, Any],
    schema_info: dict[str, Any],
    val_check: dict[str, Any],
) -> None:
    """Khung ra quyết định kiểm duyệt đơn lẻ trực diện ngay dưới bằng chứng."""
    with st.container(border=True):
        st.markdown("##### ⚖️ Ra quyết định kiểm duyệt cho cạnh này")
        is_self_loop = str(edge.get("source")) == str(edge.get("target"))
        needs_override = not ev_ctx.get("found")

        d_col1, d_col2 = st.columns(2)
        act_opts = [STATUS_APPROVED, STATUS_CHECK, STATUS_REJECTED]
        cur_status = edge.get("status") if edge.get("status") in act_opts else STATUS_APPROVED
        chosen_status = d_col1.selectbox(
            "Quyết định kiểm duyệt",
            act_opts,
            index=act_opts.index(cur_status),
            key=f"single_edge_status_{edge['id']}",
        )

        reason_code = ""
        if chosen_status == STATUS_REJECTED:
            r_keys = list(REJECTION_REASON_CODES.keys())
            cur_rc = str(edge.get("rejection_code") or "")
            reason_code = d_col2.selectbox(
                "Mã lý do loại bỏ (bắt buộc khi loại bỏ)",
                r_keys,
                index=r_keys.index(cur_rc) if cur_rc in r_keys else 0,
                format_func=lambda k: f"{REJECTION_REASON_CODES[k]} ({k})",
                key=f"single_edge_rc_{edge['id']}",
            )
        else:
            d_col2.caption(
                "Cạnh đủ điều kiện duyệt ngay."
                if val_check["ok"]
                else f"Điều kiện duyệt: {'; '.join(val_check['errors'])}"
            )

        override_reason = ""
        if chosen_status == STATUS_APPROVED and needs_override:
            override_reason = st.text_input(
                "Lý do xác nhận ngoại lệ bằng chứng (bắt buộc vì trích dẫn không khớp nguyên văn tài liệu)",
                value=str(edge.get("override_reason") or ""),
                key=f"single_edge_override_{edge['id']}",
            )

        self_loop_confirmed = False
        if chosen_status == STATUS_APPROVED and is_self_loop:
            self_loop_confirmed = st.checkbox(
                "Tôi xác nhận quan hệ tự nối (nguồn trùng đích) này có ý nghĩa thực tế trong bài toán",
                value=bool(edge.get("self_loop_confirmed", False)),
                key=f"single_edge_selfloop_{edge['id']}",
            )

        single_bypass = False
        if chosen_status == STATUS_APPROVED and schema_info.get("status_code") != "valid":
            single_bypass = st.checkbox(
                "🔓 Bỏ qua chặn Lược đồ & Tự động nạp vào Danh mục chính thức (Force Approve)",
                value=True,
                key=f"single_edge_bypass_{edge['id']}",
                help=f"Cạnh hiện vướng: {schema_info.get('issue')}. Bật tùy chọn này để duyệt thành công và tự động đồng bộ vào danh mục.",
            )

        review_note = st.text_input(
            "Ghi chú kiểm duyệt (bắt buộc khi chọn lý do 'Khác' hoặc duyệt cạnh tự nối)",
            value=str(edge.get("review_note") or ""),
            key=f"single_edge_note_{edge['id']}",
        )

        if st.button("💾 Lưu quyết định cho cạnh này", type="primary", key=f"btn_save_single_edge_{edge['id']}"):
            try:
                req = CurationReviewRequestDTO(
                    project_id=str(project.get("project_id") or project.get("name") or ""),
                    decisions=[
                        EdgeReviewDecisionDTO(
                            edge_id=str(edge["id"]),
                            action=chosen_status,
                            reason_code=reason_code,
                            note=review_note,
                            override_reason=override_reason,
                            self_loop_confirmed=self_loop_confirmed or single_bypass,
                        )
                    ],
                    apply_mode="all_or_nothing",
                    is_batch=False,
                    allow_schema_bypass=single_bypass,
                    auto_sync_catalog=True,
                    expected_revision=compute_project_revision(project),
                    request_id=uid(),
                )
                client.apply_curation_decisions(project, req)
                st.success(f"Đã cập nhật trạng thái cạnh `{edge['id']}` thành **{chosen_status}**.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_edge_edit_and_history_tabs(
    project: dict,
    client: Any,
    edge: dict,
    nodes_by_id: dict[str, dict],
) -> None:
    """Hai tab phụ: Sửa dữ kiện (nguồn/đích/quan hệ/bằng chứng) và Lịch sử thay đổi."""
    act_tab2, act_tab3 = st.tabs(
        [
            "✏️ Sửa dữ kiện (Nguồn / Đích / Quan hệ / Bằng chứng)",
            "📜 Lịch sử thay đổi của cạnh",
        ]
    )

    with act_tab2:
        st.caption(
            "Lưu ý theo ma trận toàn vẹn (mục 8.2): Khi sửa thực thể nguồn, thực thể đích, loại quan hệ, câu bằng chứng hoặc tài liệu nguồn, "
            "cạnh sẽ tự động chuyển về trạng thái **Cần kiểm tra** và xóa hiệu lực phê duyệt/ngoại lệ cũ để bắt buộc xác nhận lại."
        )
        node_ids = [str(n["id"]) for n in project.get("nodes", [])]
        rel_names = [str(r["name"]) for r in catalog_rows(project, "relations")]
        if str(edge.get("relation", "")) not in rel_names and edge.get("relation"):
            rel_names = [str(edge["relation"]), *rel_names]
        doc_ids = [str(d["id"]) for d in project.get("documents", [])]
        doc_map = {str(d["id"]): str(d.get("name", d["id"])) for d in project.get("documents", [])}

        ec1, ec2, ec3 = st.columns(3)
        new_src = ec1.selectbox(
            "Thực thể nguồn",
            node_ids,
            index=node_ids.index(edge["source"]) if edge.get("source") in node_ids else 0,
            format_func=lambda nid: f"{nodes_by_id.get(nid, {}).get('name', nid)} [{nodes_by_id.get(nid, {}).get('kind', '?')}]",
            key=f"edit_edge_src_{edge['id']}",
        )
        new_rel = ec2.selectbox(
            "Loại quan hệ (trong danh mục đã duyệt)",
            rel_names,
            index=rel_names.index(edge["relation"]) if edge.get("relation") in rel_names else 0,
            key=f"edit_edge_rel_{edge['id']}",
        )
        new_tgt = ec3.selectbox(
            "Thực thể đích",
            node_ids,
            index=node_ids.index(edge["target"]) if edge.get("target") in node_ids else 0,
            format_func=lambda nid: f"{nodes_by_id.get(nid, {}).get('name', nid)} [{nodes_by_id.get(nid, {}).get('kind', '?')}]",
            key=f"edit_edge_tgt_{edge['id']}",
        )

        new_doc_id = st.selectbox(
            "Tài liệu nguồn của bằng chứng",
            doc_ids if doc_ids else [str(edge.get("doc_id", ""))],
            index=doc_ids.index(edge["doc_id"]) if edge.get("doc_id") in doc_ids else 0,
            format_func=lambda did: doc_map.get(did, did),
            key=f"edit_edge_doc_{edge['id']}",
        )
        new_ev = st.text_area(
            "Câu trích dẫn bằng chứng",
            value=str(edge.get("evidence") or ""),
            height=90,
            key=f"edit_edge_ev_{edge['id']}",
        )
        edit_note = st.text_input("Ghi chú chỉnh sửa dữ kiện", value="", key=f"edit_edge_note_{edge['id']}")

        if st.button("✏️ Lưu chỉnh sửa dữ kiện", key=f"btn_save_edit_edge_{edge['id']}"):
            try:
                edit_req = EdgeEditRequestDTO(
                    project_id=str(project.get("project_id") or project.get("name") or ""),
                    edge_id=str(edge["id"]),
                    source=new_src,
                    target=new_tgt,
                    relation=new_rel,
                    evidence=new_ev,
                    doc_id=new_doc_id,
                    note=edit_note,
                    expected_revision=compute_project_revision(project),
                    request_id=uid(),
                )
                client.edit_edge_fact(project, edit_req)
                st.success("Đã cập nhật dữ kiện và đối chiếu lại bằng chứng.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with act_tab3:
        history = [
            h
            for h in reversed(project.get("curation_history", []))
            if h.get("target_id") == edge["id"] or edge["id"] in (h.get("affected_edge_ids") or [])
        ]
        if not history:
            st.caption("Chưa có lịch sử chỉnh sửa/kiểm duyệt cho cạnh này.")
        else:
            st.dataframe(
                [
                    {
                        "Thời điểm": h.get("at", ""),
                        "Thao tác": h.get("action", ""),
                        "Người thực hiện": h.get("actor", ""),
                        "Ghi chú": h.get("note", ""),
                    }
                    for h in history
                ],
                width='stretch',
                hide_index=True,
            )


def render_edge_evidence_and_inspector_panel(project: dict, edge_id: str) -> None:
    """Hiển thị Khung đối chiếu hai cột (Dữ kiện đề xuất vs Ngữ cảnh văn bản gốc), duyệt đơn và sửa dữ kiện."""
    edge = find_edge(project, edge_id)
    if not edge:
        st.info("Hãy chọn một dòng quan hệ trong bảng để đối chiếu bằng chứng và kiểm duyệt chi tiết.")
        return

    client = get_client()
    nodes_by_id = {str(n["id"]): n for n in project.get("nodes", [])}
    src_node = nodes_by_id.get(str(edge.get("source", "")), {})
    tgt_node = nodes_by_id.get(str(edge.get("target", "")), {})
    ev_ctx = evidence_context(project, edge)
    schema_info = inspect_edge_schema_status(project, edge)
    val_check = validate_edge_for_approval(project, edge, is_batch=False, check_existing_override=True)

    _render_edge_nav_header(project, edge)

    col_left, col_right = st.columns([1.05, 1.15])
    with col_left:
        _render_proposed_fact_card(project, edge, src_node, tgt_node, schema_info)
    with col_right:
        _render_source_context_card(project, client, edge, ev_ctx)

    _render_single_edge_decision_card(project, client, edge, ev_ctx, schema_info, val_check)
    _render_edge_edit_and_history_tabs(project, client, edge, nodes_by_id)
