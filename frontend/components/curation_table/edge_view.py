"""Giao diện Streamlit cho Bảng kiểm duyệt quan hệ & thanh thao tác lô (Trang 4)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.components.shared_curation_ui import paginate_items, render_selection_action_bar
from frontend.state.session import (
    bump_sync_nonce,
    clear_edge_selection,
    get_curation_section_state,
    reconcile_edge_selection_with_filter,
    select_all_filtered_edges,
    select_page_edges,
    set_focused_edge,
    sync_keyed_choice,
    sync_keyed_value,
    toggle_edge_selection,
)
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.schemas.curation import REJECTION_REASON_CODES
from .edge_logic import (
    build_edge_batch_preview,
    build_edge_table_rows,
    compute_edge_filter_signature,
    execute_edge_batch_apply,
    filter_and_sort_edges,
    quick_apply_edge_batch,
)


def _render_edge_filters(project: dict, s_state: dict[str, Any], filters: dict[str, Any]) -> int:
    """Hiển thị 2 tầng bộ lọc (cơ bản và nâng cao) cho bảng quan hệ; trả về số bộ lọc nâng cao đang bật."""
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    f_tag = (proj_id, int(s_state.get("filter_nonce") or 0))
    docs = project.get("documents", [])
    doc_options = ["all"] + [str(d["id"]) for d in docs]
    doc_names = {"all": "Tất cả tài liệu", **{str(d["id"]): str(d.get("name", d["id"])) for d in docs}}

    nodes = project.get("nodes", [])
    node_options = ["all"] + [str(n["id"]) for n in nodes]
    node_names = {"all": "Tất cả thực thể", **{str(n["id"]): f"{n.get('name', '')} [{n.get('kind', '')}]" for n in nodes}}

    rel_options = ["all"] + sorted({str(e.get("relation", "")) for e in project.get("edges", []) if e.get("relation")})
    kind_options = ["all"] + sorted({str(n.get("kind", "")) for n in nodes if n.get("kind")})

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
    sync_keyed_value("cur_edge_f_search", filters.get("search", ""), f_tag)
    filters["search"] = c_search.text_input(
        "Tìm kiếm từ khóa",
        placeholder="🔍 Tìm nhanh thực thể, quan hệ, trích dẫn bằng chứng...",
        label_visibility="collapsed",
        key="cur_edge_f_search",
    )
    status_opts = ["all", STATUS_CHECK, STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED]
    sync_keyed_choice("cur_edge_f_status", status_opts, filters.get("status", "all"), f_tag)
    filters["status"] = c_status.selectbox(
        "Trạng thái duyệt",
        status_opts,
        format_func=lambda x: "Tất cả trạng thái" if x == "all" else f"Trạng thái: {x}",
        label_visibility="collapsed",
        key="cur_edge_f_status",
    )

    # TẦNG 2: VÙNG MỞ RỘNG BỘ LỌC NÂNG CAO (Mặc định thu gọn, mở khi có tiêu chí đang lọc)
    with st.expander(adv_label, expanded=bool(adv_active_count > 0)):
        f1, f2, f3, f4 = st.columns(4)
        sync_keyed_choice("cur_edge_f_doc", doc_options, filters.get("doc_id", "all"), f_tag)
        filters["doc_id"] = f1.selectbox(
            "Tài liệu nguồn",
            doc_options,
            format_func=lambda x: doc_names.get(x, x),
            key="cur_edge_f_doc",
        )
        sync_keyed_choice("cur_edge_f_rel", rel_options, filters.get("relation", "all"), f_tag)
        filters["relation"] = f2.selectbox(
            "Loại quan hệ",
            rel_options,
            format_func=lambda x: "Tất cả quan hệ" if x == "all" else x,
            key="cur_edge_f_rel",
        )
        sync_keyed_choice("cur_edge_f_ent", node_options, filters.get("entity_id", "all"), f_tag)
        filters["entity_id"] = f3.selectbox(
            "Thực thể liên quan",
            node_options,
            format_func=lambda x: node_names.get(x, x),
            key="cur_edge_f_ent",
        )
        sync_keyed_choice("cur_edge_f_kind", kind_options, filters.get("entity_kind", "all"), f_tag)
        filters["entity_kind"] = f4.selectbox(
            "Loại thực thể đầu mút",
            kind_options,
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
        sync_keyed_choice("cur_edge_f_ev", ev_opts, filters.get("evidence_state", "all"), f_tag)
        filters["evidence_state"] = f5.selectbox(
            "Tình trạng bằng chứng",
            ev_opts,
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
        sync_keyed_choice("cur_edge_f_schema", sc_opts, filters.get("schema_state", "all"), f_tag)
        filters["schema_state"] = f6.selectbox(
            "Tình trạng danh mục",
            sc_opts,
            format_func=lambda x: sc_labels.get(x, x),
            key="cur_edge_f_schema",
        )
        f_reset.write("")
        f_reset.write("")
        if f_reset.button("🔄 Đặt lại lọc", key="cur_edge_btn_reset_filters", help="Xóa nhanh toàn bộ bộ lọc"):
            filters["search"] = ""
            filters["status"] = "all"
            filters["doc_id"] = "all"
            filters["relation"] = "all"
            filters["entity_id"] = "all"
            filters["entity_kind"] = "all"
            filters["evidence_state"] = "all"
            filters["schema_state"] = "all"
            filters["page"] = 1
            s_state["filter_nonce"] = int(s_state.get("filter_nonce") or 0) + 1
            s_state["page_nonce"] = int(s_state.get("page_nonce") or 0) + 1
            st.rerun()

    return adv_active_count


def _render_edge_batch_bar_and_preview(
    project: dict,
    s_state: dict[str, Any],
    filters: dict[str, Any],
    sel_ids: list[str],
) -> None:
    """Hiển thị thanh thao tác nhanh hàng loạt và khung Xem trước / Áp dụng lô."""
    with st.container(border=True):
        st.markdown(
            f"##### ⚡ Thao tác Nhanh cho **{len(sel_ids)}** Quan hệ Đang Chọn "
            "(phạm vi: các dòng đã đánh dấu theo ID)"
        )
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        sync_keyed_value("cur_batch_allow_bypass_schema", True, proj_id)
        allow_bypass = st.checkbox(
            "🔓 Cho phép duyệt cả cạnh chưa hợp lệ Lược đồ / Bỏ qua lỗi danh mục (Tự động nạp vào Danh mục chính thức)",
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
                    bump_sync_nonce("_inspector_action_nonce")
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
                    bump_sync_nonce("_inspector_action_nonce")
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
                res = quick_apply_edge_batch(
                    project,
                    sel_ids,
                    "reject",
                    reason_code="incorrect_fact",
                    note="Loại bỏ hàng loạt",
                    apply_mode="valid_only",
                )
                if res.status == "no_op":
                    st.info(f"ℹ️ Toàn bộ {res.skipped_count} cạnh đang chọn đều đã ở trạng thái Loại bỏ từ trước.")
                else:
                    bump_sync_nonce("_inspector_action_nonce")
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
                        bump_sync_nonce("_inspector_action_nonce")
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
                        bump_sync_nonce("_inspector_action_nonce")
                        st.success(
                            f"Đã áp dụng {res.applied_count} cạnh hợp lệ và giữ lại {res.skipped_count} cạnh lỗi để kiểm tra tiếp."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


def render_edge_curation_table_and_batch_bar(project: dict) -> dict[str, Any]:
    """Hiển thị bộ lọc, bảng dữ kiện, thanh chọn theo ID và thanh Xem trước / Áp dụng lô."""
    s_state = get_curation_section_state(project, "edges")
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    filters = s_state["filters"]
    adv_active_count = _render_edge_filters(project, s_state, filters)

    filtered_edges = filter_and_sort_edges(project, filters)
    s_state["ordered_edge_ids"] = [str(e["id"]) for e in filtered_edges if e.get("id")]
    filter_sig = compute_edge_filter_signature(filters)
    prev_page_sig = s_state.get("_prev_pagination_sig")
    if prev_page_sig is None:
        s_state["_prev_pagination_sig"] = filter_sig
    elif prev_page_sig != filter_sig:
        s_state["_prev_pagination_sig"] = filter_sig
        if int(filters.get("page") or 1) != 1:
            filters["page"] = 1
            s_state["page_nonce"] = int(s_state.get("page_nonce") or 0) + 1
            st.rerun()
    reconcile_edge_selection_with_filter(project, filter_sig, filtered_edges)

    if s_state.get("filter_prune_notice"):
        st.info(f"ℹ️ {s_state['filter_prune_notice']}")

    active_edge_filters = [
        f"Trạng thái: **{'Tất cả' if filters.get('status', 'all') == 'all' else filters.get('status')}**"
    ]
    if str(filters.get("search") or "").strip():
        active_edge_filters.append(f"Từ khóa: `{filters['search'].strip()}`")
    if adv_active_count > 0:
        active_edge_filters.append(f"{adv_active_count} bộ lọc nâng cao")
    st.caption(
        f"🎯 Bộ lọc đang bật: {' · '.join(active_edge_filters)} "
        f"({len(filtered_edges)}/{len(project.get('edges', []))} quan hệ khớp). "
        "Phạm vi thao tác nhanh bên dưới áp dụng cho các dòng đã tick (lưu theo ID)."
    )

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
        sync_tag=(proj_id, int(s_state.get("page_nonce") or 0)),
    )
    if page_res:
        new_page, new_size = page_res
        old_size = int(filters.get("page_size") or 25)
        if new_size != old_size:
            filters["page_size"] = new_size
            filters["page"] = 1
            s_state["page_nonce"] = int(s_state.get("page_nonce") or 0) + 1
            st.rerun()
        elif new_page != cur_page:
            filters["page"] = new_page
            st.rerun()

    display_rows = build_edge_table_rows(project, page_edges, s_state["selected_ids"])
    st.caption(
        f"Hiển thị **{len(page_edges)} / {len(filtered_edges)}** quan hệ khớp bộ lọc · "
        f"Đang chọn **{len(s_state['selected_ids'])}** quan hệ chờ xử lý."
    )

    if display_rows:
        sel_nonce = int(s_state.get("sel_editor_nonce") or 0)
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
            key=f"cur_edge_editor_{proj_id}_{sel_nonce}_{cur_page}_{filter_sig}",
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
        sync_keyed_choice(
            "cur_focus_edge_select",
            edge_opts,
            cur_focus,
            (proj_id, cur_page, cur_focus, int(s_state.get("focus_nonce") or 0)),
        )
        chosen_eid = ctrl1.selectbox(
            "🔎 Chọn dòng quan hệ để đối chiếu bằng chứng & sửa chi tiết ở khung dưới",
            edge_opts,
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

    _render_edge_batch_bar_and_preview(project, s_state, filters, list(s_state["selected_ids"]))

    return {
        "filtered_edges": filtered_edges,
        "page_edges": page_edges,
        "focused_edge_id": s_state.get("focused_edge_id", ""),
        "selected_ids": list(s_state["selected_ids"]),
    }
