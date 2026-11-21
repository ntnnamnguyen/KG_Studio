"""Tab 4: Hệ thống Gợi ý & Khử trùng Cạnh Lặp theo Bộ Ba (Triple Deduplication & Suggestion)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.domain.catalogs.service import compute_project_revision
from frontend.client import FrontendClient
from frontend.components.merge.provenance_view import render_edge_group_provenance_panel
from frontend.state.session import (
    bump_sync_nonce,
    reset_curation_state_if_project_changed,
    sync_keyed_value,
)


def render_triple_dedup_history_body(project: dict) -> None:
    """Nội dung lịch sử khử trùng cạnh lặp, cặp miễn trừ sự kiện độc lập và bảng ánh xạ edge_redirects."""
    hist = [
        h for h in project.get("curation_history", [])
        if h.get("operation") == "collapse_duplicate_edges" or h.get("action") == "collapse_duplicate_edges"
    ]
    dismissed_edges = project.get("not_duplicate_edge_pairs", [])
    edge_redirects = project.get("edge_redirects", {})
    if dismissed_edges:
        st.caption("Danh sách các cặp/nhóm cạnh đã đánh dấu **Sự kiện Độc lập (Không gộp)** (`not_duplicate_edge_pairs`):")
        st.dataframe(
            [
                {
                    "Cạnh A": d.get("edge_a_id", ""),
                    "Cạnh B / Nhóm": d.get("edge_b_id", ""),
                    "Thời điểm": d.get("at", ""),
                    "Người duyệt": d.get("actor", ""),
                    "Ghi chú": d.get("note", ""),
                }
                for d in reversed(dismissed_edges)
            ],
            width="stretch",
            hide_index=True,
        )
    if edge_redirects:
        st.caption("Bảng ánh xạ phẳng `edge_redirects` (`old_edge_id -> canonical_edge_id`):")
        st.json(edge_redirects)
    if hist:
        st.dataframe(
            [
                {
                    "Thời điểm": h.get("at", ""),
                    "Người thực hiện": h.get("actor", ""),
                    "Số nhóm gộp": h.get("groups_count", 0),
                    "Số cạnh đã thu gọn": h.get("dropped_edges_count", h.get("dropped_count", 0)),
                    "Ghi chú": h.get("note", ""),
                }
                for h in reversed(hist)
            ],
            width="stretch",
            hide_index=True,
        )
    elif not dismissed_edges and not edge_redirects:
        st.info("Chưa có phiên khử trùng cạnh lặp hoặc cặp miễn trừ nào được ghi nhận.")


def render_triple_dedup_tab(
    project: dict,
    client: FrontendClient,
    *,
    show_history: bool = True,
) -> None:
    """Nội dung Tab Khử trùng Cạnh Lặp theo Bộ Ba (Gợi ý thông minh, Chọn lọc & Đối chiếu bằng chứng)."""
    st.markdown("#### ✨ 3A. Gợi ý & Khử trùng Cạnh Lặp theo Bộ Ba (Triple Deduplication)")
    st.caption(
        "Phát hiện thông minh các nhóm bộ ba `(Nguồn – Quan hệ – Đích)` bị trùng lặp tuyệt đối, "
        "cùng cặp nút nhưng vị từ tương đồng hoặc ngược chiều Chủ động – Bị động. "
        "Hỗ trợ đối chiếu câu trích dẫn nguyên văn, hợp nhất có chọn lọc (`edge_redirects`) "
        "và đánh dấu miễn trừ cho các **sự kiện lịch sử độc lập lặp lại theo thời gian**."
    )

    proj_id = str(project.get("project_id") or project.get("name") or "default")
    rev = compute_project_revision(project)

    with st.container(border=True):
        c_thresh, c_filter, c_dis = st.columns([1.8, 1.6, 1.3])
        with c_thresh:
            thresh_key = f"triple_dedup_thresh_{proj_id}"
            sync_keyed_value(thresh_key, 0.70, (proj_id, "triple_thresh"))
            fuzzy_thresh = st.slider(
                "Ngưỡng tương đồng vị từ trên cùng cặp nút",
                min_value=0.50,
                max_value=1.00,
                step=0.05,
                key=thresh_key,
                help=(
                    "Kéo về 1.00 để chỉ lọc các cạnh trùng khớp 100% cả (Nguồn, Quan hệ, Đích). "
                    "Giảm xuống 0.65–0.80 để gợi ý thêm các cạnh có cùng cặp thực thể nhưng vị từ diễn đạt tương đồng."
                ),
            )
        with c_filter:
            filter_options = {
                "all": "Tất cả loại gợi ý bộ ba",
                "exact_triplet": "Trùng bộ ba tuyệt đối (100%)",
                "fuzzy_relation": "Cùng cặp nút · Vị từ tương đồng",
                "inverse_pair": "Đảo chiều Chủ động – Bị động",
            }
            type_filter = st.selectbox(
                "Lọc theo phân tầng gợi ý",
                options=list(filter_options.keys()),
                format_func=lambda k: filter_options[k],
                key=f"triple_dedup_type_filter_{proj_id}",
            )
        with c_dis:
            st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
            inc_dis_key = f"triple_dedup_inc_dis_{proj_id}"
            sync_keyed_value(inc_dis_key, False, (proj_id, "triple_inc_dis"))
            include_dismissed = st.checkbox(
                "Hiện cả nhóm đã giữ riêng",
                key=inc_dis_key,
                help="Hiển thị cả những nhóm cạnh đã được đánh dấu là Sự kiện độc lập (Không gộp).",
            )

        all_suggestions = client.triple_duplicate_suggestions(
            project,
            fuzzy_threshold=fuzzy_thresh,
            include_dismissed=include_dismissed,
            include_fuzzy_same_endpoints=True,
            include_inverse_pairs=True,
        )

        if type_filter != "all":
            suggestions = [g for g in all_suggestions if g.get("match_type") == type_filter]
        else:
            suggestions = all_suggestions

        if not suggestions:
            st.success(
                "✅ Đồ thị tri thức sạch sẽ! Không phát hiện nhóm bộ ba nghi trùng nào ở ngưỡng và bộ lọc hiện tại."
            )
        else:
            exact_count = sum(1 for g in suggestions if g.get("match_type") == "exact_triplet")
            fuzzy_count = sum(1 for g in suggestions if g.get("match_type") == "fuzzy_relation")
            inv_count = sum(1 for g in suggestions if g.get("match_type") == "inverse_pair")
            total_redundant_edges = sum(max(0, int(g.get("count", 1)) - 1) for g in suggestions)

            st.info(
                f"💡 Phát hiện **{len(suggestions)}** nhóm bộ ba nghi trùng "
                f"(Trùng 100%: **{exact_count}** · Vị từ tương đồng cùng cặp nút: **{fuzzy_count}** · "
                f"Đảo chiều Chủ động/Bị động: **{inv_count}**), tương ứng **{total_redundant_edges}** cạnh có thể thu gọn."
            )

            # Quản lý trạng thái chọn dòng trên bảng
            sel_map_key = f"triple_dedup_sel_map_{proj_id}_{rev}"
            if sel_map_key not in st.session_state:
                # Mặc định chọn sẵn các nhóm trùng bộ ba 100% chưa bị đánh dấu miễn trừ
                st.session_state[sel_map_key] = {
                    g["group_key"]: (g.get("match_type") == "exact_triplet" and not g.get("dismissed", False))
                    for g in suggestions
                }
            sel_map: dict[str, bool] = st.session_state[sel_map_key]

            b_col1, b_col2, b_col3, _ = st.columns([1.1, 1.1, 1.5, 2.5])
            if b_col1.button("☑️ Chọn tất cả", key=f"btn_triple_sel_all_{proj_id}", width="stretch"):
                for g in suggestions:
                    sel_map[g["group_key"]] = True
                st.session_state[f"triple_editor_ver_{proj_id}"] = st.session_state.get(f"triple_editor_ver_{proj_id}", 0) + 1
                st.rerun()
            if b_col2.button("✖️ Bỏ chọn", key=f"btn_triple_unsel_all_{proj_id}", width="stretch"):
                for g in suggestions:
                    sel_map[g["group_key"]] = False
                st.session_state[f"triple_editor_ver_{proj_id}"] = st.session_state.get(f"triple_editor_ver_{proj_id}", 0) + 1
                st.rerun()
            if b_col3.button("🎯 Chỉ chọn nhóm trùng 100%", key=f"btn_triple_sel_exact_{proj_id}", width="stretch"):
                for g in suggestions:
                    sel_map[g["group_key"]] = g.get("match_type") == "exact_triplet" and not g.get("dismissed", False)
                st.session_state[f"triple_editor_ver_{proj_id}"] = st.session_state.get(f"triple_editor_ver_{proj_id}", 0) + 1
                st.rerun()

            editor_ver = st.session_state.get(f"triple_editor_ver_{proj_id}", 0)
            table_rows: list[dict[str, Any]] = []
            for g in suggestions:
                gk = g["group_key"]
                variants = g.get("relation_variants") or [g.get("relation", "")]
                table_rows.append(
                    {
                        "Chọn": bool(sel_map.get(gk, False)),
                        "Thực thể Nguồn": str(g.get("source_name") or g.get("source", "")),
                        "Quan hệ chuẩn giữ lại": str(g.get("relation", "")),
                        "Các biến thể vị từ": " | ".join(str(v) for v in variants),
                        "Thực thể Đích": str(g.get("target_name") or g.get("target", "")),
                        "Loại gợi ý": str(g.get("match_type_label", "")),
                        "Độ tương đồng": float(g.get("score", 1.0)),
                        "Số cạnh": int(g.get("count", 0)),
                        "ID cạnh chuẩn": str(g.get("representative_id", "")),
                        "Trạng thái các cạnh": str(g.get("status_summary", "")),
                        "Lý do gợi ý": str(g.get("reason", "")),
                    }
                )

            edited_rows = st.data_editor(
                table_rows,
                key=f"triple_dedup_editor_{proj_id}_{rev}_{editor_ver}",
                width="stretch",
                hide_index=True,
                disabled=[
                    "Thực thể Nguồn",
                    "Các biến thể vị từ",
                    "Thực thể Đích",
                    "Loại gợi ý",
                    "Độ tương đồng",
                    "Số cạnh",
                    "ID cạnh chuẩn",
                    "Trạng thái các cạnh",
                    "Lý do gợi ý",
                ],
                column_config={
                    "Chọn": st.column_config.CheckboxColumn("Chọn", default=False, width="small"),
                    "Quan hệ chuẩn giữ lại": st.column_config.TextColumn(
                        "Quan hệ chuẩn giữ lại",
                        help="Có thể chỉnh sửa tên quan hệ chuẩn sau khi hợp nhất nhóm bộ ba này.",
                    ),
                    "Độ tương đồng": st.column_config.NumberColumn("Độ tương đồng", format="%.2f", width="small"),
                    "Số cạnh": st.column_config.NumberColumn("Số cạnh", format="%d", width="small"),
                },
            )

            selected_groups: list[dict[str, Any]] = []
            for idx, row in enumerate(edited_rows):
                if idx >= len(suggestions):
                    continue
                g_copy = dict(suggestions[idx])
                is_checked = bool(row.get("Chọn", False))
                sel_map[g_copy["group_key"]] = is_checked
                edited_rel = str(row.get("Quan hệ chuẩn giữ lại") or g_copy.get("relation") or "").strip()
                if edited_rel:
                    g_copy["relation"] = edited_rel
                    g_copy["canonical_relation"] = edited_rel
                if is_checked:
                    selected_groups.append(g_copy)

            selected_redundant_count = sum(max(0, int(g.get("count", 1)) - 1) for g in selected_groups)

            # Khung đối chiếu bằng chứng & đoạn trích văn bản gốc của các nhóm đang chọn
            with st.expander(
                f"🔍 Đối chiếu Bằng chứng & Đoạn trích Văn bản Gốc ({len(selected_groups)} nhóm đang chọn)",
                expanded=0 < len(selected_groups) <= 4,
            ):
                render_edge_group_provenance_panel(project, selected_groups)

            triple_nonce_key = f"_triple_dedup_nonce_{proj_id}"
            triple_nonce = int(st.session_state.get(triple_nonce_key) or 0)
            note_key = f"triple_dedup_note_{proj_id}"
            sync_keyed_value(note_key, "", (proj_id, rev, triple_nonce))
            action_note = st.text_input(
                "Ghi chú kiểm duyệt (tùy chọn)",
                key=note_key,
                placeholder="Ví dụ: Thu gọn các bộ ba trùng lặp sau khi chuẩn hóa thực thể / Đánh dấu 2 lần trùng tu khác năm...",
            )

            act_col1, act_col2 = st.columns([1.4, 1.4])
            with act_col1:
                if st.button(
                    f"⚡ Hợp nhất {len(selected_groups)} nhóm đã chọn (Thu gọn {selected_redundant_count} cạnh)",
                    type="primary",
                    width="stretch",
                    disabled=len(selected_groups) == 0,
                    key=f"btn_collapse_selected_triples_{proj_id}",
                    help="Giữ lại cạnh chuẩn ưu tiên trạng thái cao nhất, dồn 100% bằng chứng nguyên văn và cập nhật edge_redirects.",
                ):
                    res = client.collapse_duplicate_edges(
                        project,
                        selected_groups=selected_groups,
                        note=action_note.strip() or f"Hợp nhất có chọn lọc {len(selected_groups)} nhóm bộ ba.",
                    )
                    bump_sync_nonce(triple_nonce_key)
                    reset_curation_state_if_project_changed(project, force=True)
                    st.success(
                        f"✅ Đã hợp nhất thành công {len(selected_groups)} nhóm, thu gọn {res.merged_duplicate_edges} cạnh trùng lặp!"
                    )
                    st.rerun()

            with act_col2:
                if st.button(
                    f"🚫 Đánh dấu {len(selected_groups)} nhóm là Sự kiện Độc lập (Không gộp)",
                    width="stretch",
                    disabled=len(selected_groups) == 0,
                    key=f"btn_dismiss_selected_triples_{proj_id}",
                    help="Lưu vào danh sách miễn trừ not_duplicate_edge_pairs để bảo vệ các sự kiện lịch sử khác thời điểm và không gợi ý lại.",
                ):
                    dis_res = client.mark_edge_groups_not_duplicate_bulk(
                        project,
                        selected_groups,
                        note=action_note.strip() or "Sự kiện lịch sử độc lập (giữ riêng, không gộp)",
                    )
                    bump_sync_nonce(triple_nonce_key)
                    reset_curation_state_if_project_changed(project, force=True)
                    st.success(
                        f"✅ Đã đánh dấu {dis_res.get('added_count', len(selected_groups))} nhóm bộ ba là Sự kiện Độc lập!"
                    )
                    st.rerun()

    if show_history:
        hist = [
            h for h in project.get("curation_history", [])
            if h.get("operation") == "collapse_duplicate_edges" or h.get("action") == "collapse_duplicate_edges"
        ]
        dismissed_edges = project.get("not_duplicate_edge_pairs", [])
        edge_redirects = project.get("edge_redirects", {})
        with st.expander(
            f"📜 Lịch sử Khử trùng ({len(hist)} phiên) · Miễn trừ ({len(dismissed_edges)} cặp) · Ánh xạ Cạnh ({len(edge_redirects)} chuyển hướng)",
            expanded=False,
        ):
            render_triple_dedup_history_body(project)
