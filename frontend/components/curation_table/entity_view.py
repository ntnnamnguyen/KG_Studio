"""Giao diện Streamlit cho Bảng danh sách thực thể và thao tác hàng loạt thực thể (Trang 4)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows
from backend.domain.curation.service import duplicate_suggestions
from backend.facade import get_facade
from frontend.components.shared_curation_ui import paginate_items, render_selection_action_bar
from frontend.state.session import (
    clear_entity_selection,
    filter_edges_by_entity,
    get_curation_section_state,
    reconcile_entity_selection_with_filter,
    select_all_filtered_entities,
    select_page_entities,
    set_active_curation_section,
    set_focused_entity,
    stage_entities_for_merge,
    toggle_entity_selection,
)
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_REJECTED
from .entity_logic import build_entity_table_rows, filter_and_sort_entities


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
        dup_ids = {
            str(x)
            for s in sugs
            for x in (
                s.get("keep_id", s.get("node_a", {}).get("id")),
                s.get("drop_id", s.get("node_b", {}).get("id")),
            )
        }
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
            "Chỉ hiện thực thể đang nằm trong cặp nghi trùng" + (f" ({len(dup_ids)} thực thể)" if dup_active else " (bấm để quét)"),
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
