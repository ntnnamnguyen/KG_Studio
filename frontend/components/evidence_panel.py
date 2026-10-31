"""Khung đối chiếu dữ kiện & bằng chứng hai cột và bảng sửa hồ sơ thực thể (Trang 5)."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows, compute_project_revision
from backend.domain.curation.service import (
    evidence_context,
    find_document,
    find_edge,
    find_node,
    inspect_edge_schema_status,
    validate_edge_for_approval,
)
from frontend.client import get_client
from frontend.state.session import (
    filter_edges_by_entity,
    navigate_to_edc_proposal_from_curation,
    set_focused_edge,
    stage_entities_for_merge,
)
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.schemas.curation import (
    REJECTION_REASON_CODES,
    CurationReviewRequestDTO,
    EdgeEditRequestDTO,
    EdgeReviewDecisionDTO,
    EntityEditRequestDTO,
)
from shared.text_utils import uid


def format_highlighted_evidence_html(ev_ctx: dict[str, Any]) -> str:
    """Tạo đoạn HTML an toàn (escape đầy đủ ký tự đặc biệt) đánh dấu nổi bật câu bằng chứng trong đoạn văn nguồn."""
    if not ev_ctx.get("found"):
        reason = html.escape(str(ev_ctx.get("reason") or "Không tìm thấy câu trích dẫn nguyên văn trong tài liệu."))
        return f"<div style='padding:10px;border-left:4px solid #d97706;background:#fffbeb;color:#92400e;'>{reason}</div>"

    before = html.escape(str(ev_ctx.get("before_text") or ""))
    quote = html.escape(str(ev_ctx.get("quote") or ""))
    after = html.escape(str(ev_ctx.get("after_text") or ""))
    return (
        "<div style='padding:12px;border:1px solid #cbd5e1;border-radius:6px;background:#f8fafc;"
        "line-height:1.65;white-space:pre-wrap;font-size:0.95rem;'>"
        f"{before}"
        f"<mark style='background:#fde047;padding:2px 4px;border-radius:3px;font-weight:600;'>{quote}</mark>"
        f"{after}"
        "</div>"
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

    st.markdown(f"#### 🔬 Đối chiếu Dữ kiện & Bằng chứng (`{edge['id']}`)")

    col_left, col_right = st.columns([1.05, 1.15])

    # --- CỘT TRÁI: DỮ KIỆN ĐƯỢC ĐỀ XUẤT & CỔNG DANH MỤC ---
    with col_left:
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

            # Nếu bị chặn bởi đề xuất EDC ở Trang 4 -> hiển thị nút liên kết trực tiếp sang Trang 4
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

    # --- CỘT PHẢI: NGỮ CẢNH VĂN BẢN GỐC & CHỌN VỊ TRÍ BẰNG CHỨNG ---
    with col_right:
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

    # --- KHUNG RA QUYẾT ĐỊNH KIỂM DUYỆT ĐƠN LẺ & SỬA DỮ KIỆN ---
    act_tab1, act_tab2, act_tab3 = st.tabs(
        [
            "⚖️ Ra quyết định kiểm duyệt cạnh này",
            "✏️ Sửa dữ kiện (Nguồn / Đích / Quan hệ / Bằng chứng)",
            "📜 Lịch sử thay đổi của cạnh",
        ]
    )

    with act_tab1:
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


def render_entity_profile_inspector(project: dict, node_id: str) -> None:
    """Hiển thị và chỉnh sửa hồ sơ chi tiết của một thực thể độc lập ở Khu vực B (mục 6.2 & 6.3)."""
    node = find_node(project, node_id)
    if not node:
        st.info("Hãy chọn một thực thể trong bảng để xem và chỉnh sửa hồ sơ.")
        return

    client = get_client()
    nodes_by_id = {str(n["id"]): n for n in project.get("nodes", [])}
    approved_types = [str(t["name"]) for t in catalog_rows(project, "entity_types")]
    cur_kind = str(node.get("kind") or "")
    type_options = approved_types if cur_kind in approved_types else [cur_kind, *approved_types]

    st.markdown(f"#### 🏛️ Hồ sơ Thực thể: `{node.get('name', '')}` (`{node['id']}`)")

    col_form, col_edges = st.columns([1.05, 1.15])

    with col_form:
        with st.container(border=True):
            st.markdown("##### ✏️ Chỉnh sửa hồ sơ thực thể (Không cần gộp)")
            st.caption(
                "Quy tắc toàn vẹn (mục 8.2): Đổi tên hiển thị, bí danh hoặc mô tả sẽ giữ nguyên ID thực thể và trạng thái các cạnh. "
                "Nếu đổi **Loại thực thể**, các cạnh nối với thực thể này (trừ cạnh đã Loại bỏ) sẽ chuyển về **Cần kiểm tra**."
            )
            new_name = st.text_input("Tên chuẩn hiển thị", value=str(node.get("name", "")), key=f"ent_edit_name_{node['id']}")
            new_kind = st.selectbox(
                "Loại thực thể (chỉ cho phép chọn loại đã có trong danh mục đã duyệt)",
                type_options,
                index=type_options.index(cur_kind) if cur_kind in type_options else 0,
                key=f"ent_edit_kind_{node['id']}",
            )
            new_aliases_str = st.text_input(
                "Bí danh (phân tách bằng dấu chấm phẩy `;`)",
                value="; ".join(node.get("aliases", [])),
                key=f"ent_edit_aliases_{node['id']}",
            )
            new_desc = st.text_area(
                "Mô tả tổng hợp",
                value=str(node.get("description") or ""),
                height=90,
                key=f"ent_edit_desc_{node['id']}",
            )
            edit_note = st.text_input("Ghi chú cập nhật hồ sơ", value="", key=f"ent_edit_note_{node['id']}")

            if st.button("💾 Lưu hồ sơ thực thể", type="primary", key=f"btn_save_entity_{node['id']}"):
                try:
                    req = EntityEditRequestDTO(
                        project_id=str(project.get("project_id") or project.get("name") or ""),
                        node_id=str(node["id"]),
                        name=new_name,
                        kind=new_kind,
                        description=new_desc,
                        aliases=[x.strip() for x in new_aliases_str.split(";") if x.strip()],
                        note=edit_note,
                        expected_revision=compute_project_revision(project),
                        request_id=uid(),
                    )
                    res = client.edit_entity_profile(project, req)
                    inv_count = len(res.affected_edge_ids)
                    msg = f"Đã cập nhật hồ sơ thực thể `{new_name}`."
                    if inv_count > 0:
                        msg += f" Đã chuyển {inv_count} cạnh liên kết về trạng thái Cần kiểm tra do đổi loại thực thể."
                    st.success(msg)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            # Liên kết sang Trang 4 nếu thực thể còn đề xuất loại EDC
            prop_ids = list(node.get("schema_proposal_ids", []))
            if prop_ids:
                st.divider()
                st.caption("Đề xuất loại thực thể EDC liên quan:")
                for pid in prop_ids:
                    if st.button(
                        f"🔗 Mở đề xuất loại `{pid}` ở Trang 4",
                        key=f"btn_jump_p04_from_node_{node['id']}_{pid}",
                    ):
                        navigate_to_edc_proposal_from_curation(
                            project,
                            str(pid),
                            node_id=str(node["id"]),
                            section="entities",
                        )
                        st.rerun()

    with col_edges:
        with st.container(border=True):
            st.markdown("##### 🔗 Các quan hệ đi ra / đi vào thực thể này")
            connected = [
                e
                for e in project.get("edges", [])
                if e.get("source") == node["id"] or e.get("target") == node["id"]
            ]
            if not connected:
                st.info("Thực thể này hiện chưa có cạnh nối nào (Thực thể cô lập — bậc kết nối = 0).")
            else:
                st.dataframe(
                    [
                        {
                            "ID cạnh": e["id"],
                            "Chiều": "Đi ra (Nguồn)" if e.get("source") == node["id"] else "Đi vào (Đích)",
                            "Nguồn": nodes_by_id.get(str(e.get("source", "")), {}).get("name", ""),
                            "Quan hệ": e.get("relation", ""),
                            "Đích": nodes_by_id.get(str(e.get("target", "")), {}).get("name", ""),
                            "Trạng thái": e.get("status", ""),
                        }
                        for e in connected
                    ],
                    width='stretch',
                    hide_index=True,
                )
                je1, je2 = st.columns([2.0, 1.2])
                jump_eid = je1.selectbox(
                    "Chọn cạnh để mở đối chiếu bằng chứng ở Khu vực A",
                    [str(e["id"]) for e in connected],
                    key=f"ent_jump_edge_sel_{node['id']}",
                )
                if je2.button("🔬 Mở cạnh này ở Khu vực A", width='stretch', key=f"btn_ent_jump_edge_{node['id']}"):
                    filter_edges_by_entity(project, str(node["id"]))
                    set_focused_edge(project, jump_eid)
                    st.rerun()

            if node.get("merged_from"):
                st.divider()
                st.caption(f"Lịch sử gộp vào thực thể này ({len(node['merged_from'])} thực thể cũ):")
                st.dataframe(
                    [
                        {
                            "ID cũ": m.get("id", ""),
                            "Tên cũ": m.get("name", ""),
                            "Loại cũ": m.get("kind", ""),
                            "Gộp lúc": m.get("merged_at", ""),
                        }
                        for m in node["merged_from"]
                    ],
                    width='stretch',
                    hide_index=True,
                )

