"""Tab 1: Bàn gộp thực thể theo quy trình 3 bước, phát hiện nghi trùng và gộp hàng loạt."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows
from backend.domain.curation.service import duplicate_suggestions
from frontend.client import FrontendClient
from frontend.components.merge.provenance_view import render_entity_provenance_panel
from frontend.state.session import (
    bump_sync_nonce,
    reset_curation_state_if_project_changed,
    reset_edc_state_if_project_changed,
    stage_entities_for_merge,
    sync_keyed_value,
    update_merge_draft,
)
from shared.text_utils import normal
from .entity_logic import (
    _format_gazetteer_merge_notice,
    build_entity_merge_preview,
    execute_entity_merge_apply,
)


def _render_bulk_duplicate_entity_section(
    project: dict,
    client: FrontendClient,
    m_state: dict[str, Any],
    nodes_by_id: dict[str, dict],
) -> None:
    """Phần 1: Danh sách cặp thực thể nghi trùng, chọn nhiều, gộp DSU hàng loạt và chuyển vào bàn gộp."""
    with st.container(border=True):
        st.markdown("#### 🔍 1. Ứng viên Thực thể Nghi trùng & Gộp Hàng loạt (Bulk Entity Merge)")
        st.caption(
            "Hệ thống phát hiện các cặp thực thể trùng tên chuẩn hóa, giao nhau tên/bí danh hoặc gần giống chuỗi. "
            "Hỗ trợ **chọn nhiều và gộp hàng loạt** an toàn theo thuật toán cụm liên thông (DSU) bảo toàn bậc kết nối."
        )
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        sc1, sc2 = st.columns([1.6, 2.4])
        sync_keyed_value(
            "merge_fuzzy_slider",
            float(m_state.get("fuzzy_threshold", 0.82)),
            (proj_id, "ent_fuzzy"),
        )
        fuzzy_val = sc1.slider(
            "Ngưỡng tương đồng tên thực thể (Fuzzy threshold)",
            min_value=0.0,
            max_value=0.98,
            step=0.02,
            key="merge_fuzzy_slider",
        )
        m_state["fuzzy_threshold"] = fuzzy_val
        raw_suggestions = duplicate_suggestions(project, fuzzy_threshold=fuzzy_val)
        suggestions = [
            s for s in raw_suggestions
            if str(s.get("node_a", {}).get("id")) != str(s.get("node_b", {}).get("id"))
            and str(s.get("node_a", {}).get("id")) in nodes_by_id
            and str(s.get("node_b", {}).get("id")) in nodes_by_id
        ]
        sc2.caption(
            f"Tìm thấy **{len(suggestions)}** cặp nghi trùng · "
            f"Đã đánh dấu **{len(project.get('not_duplicate_pairs', []))}** cặp khác đối tượng."
        )

        sel_cand_pairs_key = f"selected_cand_pairs_{project.get('project_id', 'curr')}"
        if sel_cand_pairs_key not in st.session_state:
            st.session_state[sel_cand_pairs_key] = set()

        valid_pair_keys = {
            f"{s['node_a']['id']}___{s['node_b']['id']}"
            for s in suggestions
            if str(s.get("node_a", {}).get("id")) != str(s.get("node_b", {}).get("id"))
            and str(s.get("node_a", {}).get("id")) in nodes_by_id
            and str(s.get("node_b", {}).get("id")) in nodes_by_id
        }
        st.session_state[sel_cand_pairs_key] = {
            k for k in st.session_state[sel_cand_pairs_key]
            if k in valid_pair_keys
        }

        if suggestions:
            c_btn1, c_btn2, c_btn3, _ = st.columns([1.3, 1.8, 1.2, 2.0])
            if c_btn1.button("☑️ Chọn tất cả", key="btn_sel_all_cand_pairs", width='stretch'):
                st.session_state[sel_cand_pairs_key] = {
                    f"{s['node_a']['id']}___{s['node_b']['id']}" for s in suggestions
                }
                st.rerun()

            safe_pairs = [s for s in suggestions if not s.get("kind_conflict")]
            if c_btn2.button(
                f"🛡️ Chọn cặp cùng loại ({len(safe_pairs)})",
                key="btn_sel_safe_cand_pairs",
                width='stretch',
                help="Chọn nhanh các cặp có cùng loại thực thể (không gây xung đột schema)",
            ):
                st.session_state[sel_cand_pairs_key] = {
                    f"{s['node_a']['id']}___{s['node_b']['id']}" for s in safe_pairs
                }
                st.rerun()

            if c_btn3.button("✖️ Bỏ chọn", key="btn_clear_cand_pairs", width='stretch'):
                st.session_state[sel_cand_pairs_key] = set()
                st.rerun()

            cur_selected = st.session_state[sel_cand_pairs_key]
            table_cand_rows = [
                {
                    "pair_key": f"{s['node_a']['id']}___{s['node_b']['id']}",
                    "id_a": str(s["node_a"]["id"]),
                    "id_b": str(s["node_b"]["id"]),
                    "Chọn": f"{s['node_a']['id']}___{s['node_b']['id']}" in cur_selected,
                    "Cặp": f"#{idx}",
                    "Thực thể A": f"{s['node_a']['name']} [{s['node_a'].get('kind', '')}] (Bậc: {s['degree_a']})",
                    "Thực thể B": f"{s['node_b']['name']} [{s['node_b'].get('kind', '')}] (Bậc: {s['degree_b']})",
                    "Lý do nghi trùng": s["reason"],
                    "Điểm tương đồng": s["score"],
                    "Khác loại?": "⚠️ Khác loại" if s.get("kind_conflict") else "Cùng loại",
                }
                for idx, s in enumerate(suggestions, 1)
            ]
            edited_cands = st.data_editor(
                table_cand_rows,
                key=f"editor_cand_pairs_{len(suggestions)}_{fuzzy_val}",
                width='stretch',
                hide_index=True,
                disabled=[
                    "pair_key",
                    "id_a",
                    "id_b",
                    "Cặp",
                    "Thực thể A",
                    "Thực thể B",
                    "Lý do nghi trùng",
                    "Điểm tương đồng",
                    "Khác loại?",
                ],
                column_config={
                    "pair_key": None,
                    "id_a": None,
                    "id_b": None,
                    "Chọn": st.column_config.CheckboxColumn("Chọn", default=False),
                },
            )

            new_selected = {r["pair_key"] for r in edited_cands if r.get("Chọn")}
            if new_selected != cur_selected:
                st.session_state[sel_cand_pairs_key] = new_selected
                st.rerun()

            sel_keys = list(st.session_state[sel_cand_pairs_key])
            selected_pairs_to_merge: list[tuple[str, str]] = []
            for k in sel_keys:
                parts = k.split("___")
                if len(parts) == 2 and parts[0] != parts[1]:
                    if parts[0] in nodes_by_id and parts[1] in nodes_by_id:
                        selected_pairs_to_merge.append((parts[0], parts[1]))

            if selected_pairs_to_merge:
                with st.container(border=True):
                    st.markdown(f"##### ⚡ Thao tác Nhanh cho **{len(selected_pairs_to_merge)}** Cặp Thực thể Đang Chọn")
                    sync_keyed_value("cb_bulk_ent_collapse", False, (proj_id, "bulk_ent_collapse"))
                    cb_bulk_ent_collapse = st.checkbox(
                        "Tự động hợp nhất các cạnh trùng bộ ba (dồn bằng chứng đầy đủ)",
                        key="cb_bulk_ent_collapse",
                        help="Nếu việc đổi đầu mút dẫn tới các cạnh có cùng nguồn, quan hệ và đích, hệ thống sẽ tự động dồn bằng chứng nguyên văn và xóa cạnh thừa.",
                    )
                    act_col1, act_col2 = st.columns([1.5, 1.5])
                    if act_col1.button(
                        f"⚡ Gộp nhanh {len(selected_pairs_to_merge)} cặp đã chọn (Bulk Merge)",
                        type="primary",
                        disabled=len(selected_pairs_to_merge) == 0,
                        width='stretch',
                        key="btn_bulk_merge_entities",
                        help="Tự động nhóm theo cụm liên thông (DSU), giữ lại ID có bậc kết nối cao nhất, hợp nhất bí danh, tài liệu và chuyển hướng cạnh.",
                    ):
                        try:
                            res = client.apply_bulk_entity_merges(
                                project, selected_pairs_to_merge, collapse_edges=cb_bulk_ent_collapse
                            )
                            st.session_state[sel_cand_pairs_key] = set()
                            dup_msg = f" Đã hợp nhất {res.merged_duplicate_edges} cạnh trùng bộ ba." if getattr(res, "merged_duplicate_edges", 0) > 0 else ""
                            gaz_msg = _format_gazetteer_merge_notice(project)
                            done_msg = (
                                f"Đã gộp thành công {res.applied_count} thực thể trong {len(selected_pairs_to_merge)} cặp đã chọn. "
                                f"Cập nhật {len(res.affected_edge_ids)} cạnh (Đổi {res.changed_endpoint_count} đầu mút).{dup_msg}{gaz_msg}"
                            )
                            m_state.setdefault("flash_messages", []).append(done_msg)
                            if gaz_msg:
                                st.toast("📚 Đã thêm bí danh vào Từ điển Dự án!")
                            st.success(done_msg)
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

                    if act_col2.button(
                        f"🚫 Đánh dấu {len(selected_pairs_to_merge)} cặp là Khác đối tượng",
                        width='stretch',
                        key="btn_bulk_mark_not_dup",
                        help="Lưu tất cả các cặp đã chọn vào danh sách 'Khác đối tượng' để không gợi ý lại trong tương lai.",
                    ):
                        client.mark_pairs_not_duplicate_bulk(
                            project,
                            selected_pairs_to_merge,
                            note="Xác nhận hàng loạt là khác đối tượng",
                        )
                        st.session_state[sel_cand_pairs_key] = set()
                        st.success(f"Đã đánh dấu {len(selected_pairs_to_merge)} cặp là khác đối tượng.")
                        st.rerun()

            st.caption("Hoặc chọn từng cặp riêng lẻ để đưa vào bàn gộp 3 bước tùy chỉnh chuyên sâu:")
            pair_indices = list(range(len(suggestions)))
            pc1, pc2, pc3 = st.columns([2.4, 1.2, 1.3])
            chosen_p_idx = pc1.selectbox(
                "Chọn cặp ứng viên đơn lẻ để tinh chỉnh",
                pair_indices,
                format_func=lambda i: (
                    f"Cặp #{i + 1}: {suggestions[i]['node_a']['name']} [{suggestions[i]['node_a'].get('kind', '')}] "
                    f"↔ {suggestions[i]['node_b']['name']} [{suggestions[i]['node_b'].get('kind', '')}] ({suggestions[i]['reason']})"
                ),
                key="merge_cand_pair_select",
            )
            chosen_pair = suggestions[chosen_p_idx]
            na_id = str(chosen_pair["node_a"]["id"])
            nb_id = str(chosen_pair["node_b"]["id"])

            if pc2.button("➕ Đưa cặp này vào bàn gộp", width='stretch', key="btn_stage_cand_pair"):
                keep_default = na_id if chosen_pair["degree_a"] >= chosen_pair["degree_b"] else nb_id
                stage_entities_for_merge(project, [na_id, nb_id], keep_id=keep_default, switch_to_merge=True)
                st.rerun()

            if pc3.button("🚫 Khác đối tượng (Đơn lẻ)", width='stretch', key="btn_mark_not_dup"):
                client.mark_pair_not_duplicate(project, na_id, nb_id, note="Người duyệt xác nhận khác đối tượng")
                st.success("Đã lưu cặp này vào danh sách 'Khác đối tượng'.")
                st.rerun()
        else:
            st.info("Không có cặp thực thể nghi trùng nào ở ngưỡng hiện tại.")


def _render_three_step_entity_workbench(
    project: dict,
    m_state: dict[str, Any],
    nodes: list[dict],
    nodes_by_id: dict[str, dict],
    degrees: dict[str, dict[str, int]],
) -> None:
    """Phần 2: Bàn gộp thực thể theo quy trình 3 bước."""
    with st.container(border=True):
        st.markdown("#### 🔀 2. Bàn Gộp Thực thể theo Quy trình 3 Bước (Hỗ trợ gộp 2..N thực thể tùy biến)")

        st.markdown("##### Bước 1 — Chọn và so sánh các thực thể cần gộp")
        all_node_ids = [str(n["id"]) for n in nodes if n.get("id")]
        cur_members = [nid for nid in m_state.get("member_ids", []) if nid in nodes_by_id]
        cur_proj_id = str(m_state.get("project_id") or project.get("project_id") or project.get("name") or "")
        target_sync_tag = (cur_proj_id, int(m_state.get("sync_nonce") or 0))
        if st.session_state.get("_merge_members_synced_tag") != target_sync_tag or "merge_multiselect_members" not in st.session_state:
            st.session_state["merge_multiselect_members"] = list(cur_members)
            st.session_state["_merge_members_synced_tag"] = target_sync_tag
        else:
            st.session_state["merge_multiselect_members"] = [
                nid for nid in st.session_state.get("merge_multiselect_members", []) if nid in nodes_by_id
            ]

        selected_members = st.multiselect(
            "Chọn từ 2 thực thể trở lên để so sánh và gộp thành 1 thực thể duy nhất",
            all_node_ids,
            format_func=lambda nid: (
                f"{nodes_by_id[nid].get('name', nid)} [{nodes_by_id[nid].get('kind', '?')}] "
                f"(Bậc: {degrees.get(nid, {'total': 0})['total']} · ID: {nid})"
            ),
            key="merge_multiselect_members",
        )
        if selected_members != cur_members:
            m_state["member_ids"] = []
            stage_entities_for_merge(project, selected_members, switch_to_merge=False)
            st.session_state["_merge_members_synced_tag"] = (
                cur_proj_id,
                int(m_state.get("sync_nonce") or 0),
            )
            st.rerun()

        if len(selected_members) < 2:
            st.info("Hãy chọn ít nhất **2 thực thể** (từ bảng gợi ý ở trên hoặc từ ô tìm kiếm) để bắt đầu so sánh và gộp.")
            return

        member_nodes = [nodes_by_id[nid] for nid in selected_members if nid in nodes_by_id]
        st.dataframe(
            [
                {
                    "ID thực thể": n["id"],
                    "Tên hiện tại": n.get("name", ""),
                    "Loại thực thể": n.get("kind", ""),
                    "Bí danh hiện có": "; ".join(n.get("aliases", [])),
                    "Mô tả": n.get("description", ""),
                    "Số tài liệu": len(n.get("documents", [])),
                    "Bậc kết nối": degrees.get(str(n["id"]), {"total": 0})["total"],
                    "Đề xuất EDC": ", ".join(n.get("schema_proposal_ids", [])),
                }
                for n in member_nodes
            ],
            width='stretch',
            hide_index=True,
        )

        with st.expander("🔍 Đối chiếu Ngữ cảnh Văn bản & Đoạn trích Gốc (Data Provenance)", expanded=True):
            render_entity_provenance_panel(project, selected_members)

        st.markdown("##### Bước 2 — Giải quyết xung đột trường dữ liệu & Chọn hồ sơ chuẩn")
        distinct_kinds = list(dict.fromkeys(str(n.get("kind") or "").strip() for n in member_nodes if n.get("kind")))
        has_kind_conflict = len({normal(k) for k in distinct_kinds if k}) > 1

        approved_types = [str(t["name"]) for t in catalog_rows(project, "entity_types")]
        for k in distinct_kinds:
            if k and k not in approved_types:
                approved_types.insert(0, k)

        c_keep, c_name, c_kind = st.columns(3)
        need_step2_sync = st.session_state.get("_merge_step2_synced_tag") != target_sync_tag
        cur_keep = str(m_state.get("keep_id") or selected_members[0])
        if cur_keep not in selected_members:
            cur_keep = selected_members[0]
        if need_step2_sync or st.session_state.get("merge_keep_id_select") not in selected_members:
            st.session_state["merge_keep_id_select"] = cur_keep
        chosen_keep = c_keep.selectbox(
            "Thực thể đích giữ lại ID (`keep_id`)",
            selected_members,
            format_func=lambda nid: f"{nodes_by_id[nid].get('name', nid)} ({nid})",
            key="merge_keep_id_select",
        )

        name_suggestions = list(dict.fromkeys(str(n.get("name", "")) for n in member_nodes if n.get("name")))
        cur_canon_name = str(m_state.get("canonical_name") or nodes_by_id[chosen_keep].get("name", ""))
        if need_step2_sync or "merge_canon_name_input" not in st.session_state:
            st.session_state["merge_canon_name_input"] = cur_canon_name
        chosen_name = c_name.text_input(
            f"Tên chuẩn hiển thị (Gợi ý: {', '.join(name_suggestions[:3])})",
            key="merge_canon_name_input",
        )

        kind_choices = approved_types if approved_types else [""]
        cur_canon_kind = str(m_state.get("canonical_kind") or nodes_by_id[chosen_keep].get("kind", ""))
        fallback_kind = cur_canon_kind if cur_canon_kind in kind_choices else kind_choices[0]
        if need_step2_sync or st.session_state.get("merge_canon_kind_select") not in kind_choices:
            st.session_state["merge_canon_kind_select"] = fallback_kind
        chosen_kind = c_kind.selectbox(
            "Loại thực thể chuẩn sau khi gộp",
            kind_choices,
            key="merge_canon_kind_select",
        )

        kind_note = str(m_state.get("kind_resolution_note") or "")
        if has_kind_conflict:
            st.warning(
                f"⚠️ **Xung đột loại thực thể:** Các thực thể đang chọn có loại khác nhau ({', '.join(distinct_kinds)}). "
                "Bắt buộc nhập lý do chọn loại chuẩn; các cạnh nối với thực thể đổi loại sẽ chuyển về **Cần kiểm tra**."
            )
            if need_step2_sync or "merge_kind_note_input" not in st.session_state:
                st.session_state["merge_kind_note_input"] = kind_note
            kind_note = st.text_input(
                "Lý do giải quyết xung đột loại thực thể (bắt buộc khi gộp thực thể khác loại)",
                key="merge_kind_note_input",
            )

        if need_step2_sync or "merge_canon_desc_input" not in st.session_state:
            st.session_state["merge_canon_desc_input"] = str(m_state.get("canonical_description") or "")
        chosen_desc = st.text_area(
            "Mô tả tổng hợp sau khi gộp",
            height=80,
            key="merge_canon_desc_input",
        )
        if need_step2_sync or "merge_note_input" not in st.session_state:
            st.session_state["merge_note_input"] = str(m_state.get("note") or "")
        merge_note = st.text_input(
            "Ghi chú phiên gộp thực thể",
            key="merge_note_input",
        )
        if need_step2_sync:
            st.session_state["_merge_step2_synced_tag"] = target_sync_tag

        if (
            chosen_keep != m_state.get("keep_id")
            or chosen_name != m_state.get("canonical_name")
            or chosen_kind != m_state.get("canonical_kind")
            or kind_note != m_state.get("kind_resolution_note")
            or chosen_desc != m_state.get("canonical_description")
            or merge_note != m_state.get("note")
        ):
            update_merge_draft(
                project,
                keep_id=chosen_keep,
                canonical_name=chosen_name,
                canonical_kind=chosen_kind,
                kind_resolution_note=kind_note,
                canonical_description=chosen_desc,
                note=merge_note,
            )

        st.markdown("##### Bước 3 — Xem trước tác động & Xác nhận gộp thực thể")
        if st.button("👁️ Xem trước tác động gộp", width='stretch', key="btn_preview_entity_merge"):
            build_entity_merge_preview(project)
            st.rerun()

        active_prev = m_state.get("active_preview")
        if isinstance(active_prev, dict):
            if active_prev.get("errors"):
                for err in active_prev["errors"]:
                    st.error(f"⛔ {err}")
            for warn in active_prev.get("warnings", []):
                st.warning(f"⚠️ {warn}")

            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric("Số thực thể gộp", f"{len(active_prev.get('member_ids', []))} → 1")
            pm2.metric(
                "Cạnh duy nhất bị ảnh hưởng",
                f"{active_prev.get('affected_edge_count', 0)} (Đầu mút đổi: {active_prev.get('changed_endpoint_count', 0)})",
            )
            pm3.metric("Cạnh tự nối mới phát sinh", len(active_prev.get("new_self_loop_ids", [])))
            pm4.metric("Nhóm cạnh có vẻ trùng sau gộp", len(active_prev.get("apparent_duplicate_groups", [])))

            keep_preview_id = str(active_prev.get("keep_id") or chosen_keep)
            dropped_preview_ids = [
                mid for mid in (active_prev.get("member_ids") or [])
                if str(mid) != keep_preview_id
            ]
            dropped_labels = [
                f"{nodes_by_id.get(str(mid), {}).get('name', mid)} ({mid})"
                for mid in dropped_preview_ids
            ]
            with st.container(border=True):
                st.markdown(
                    f"**📋 Tóm tắt tác động trước khi xác nhận:**\n"
                    f"- **Thực thể giữ lại (đích):** `{active_prev.get('canonical_name', '')}` (`{keep_preview_id}`)\n"
                    f"- **Thực thể bị gộp & đóng băng ID:** {', '.join(f'`{lbl}`' for lbl in dropped_labels) or '(Không có)'}\n"
                    f"- **Bí danh bảo toàn & dự kiến nạp vào Từ điển Dự án (`domain_gazetteer`):** "
                    f"`{'; '.join(active_prev.get('merged_aliases', [])) or '(Không có)'}`"
                )
            st.caption("Toàn bộ ID cạnh và bằng chứng được giữ nguyên 100% (không tự xóa ngầm bất kỳ cạnh nào).")

            proj_id = str(project.get("project_id") or project.get("name") or "default")
            collapse_nonce_key = f"_ent_manual_collapse_nonce_{proj_id}"
            collapse_nonce = int(st.session_state.get(collapse_nonce_key) or 0)
            sync_keyed_value("cb_manual_ent_collapse", False, (proj_id, collapse_nonce))
            n_count = len(active_prev.get("member_ids", []))
            cb_manual_ent_collapse = st.checkbox(
                "Tự động hợp nhất các cạnh trùng bộ ba (dồn bằng chứng đầy đủ)",
                key="cb_manual_ent_collapse",
                help="Nếu việc đổi đầu mút thực thể dẫn tới các cạnh có cùng nguồn, quan hệ và đích, hệ thống sẽ tự động gộp thành 1 cạnh duy nhất và dồn toàn bộ trích dẫn nguyên văn lại.",
            )
            if st.button(
                f"✅ Gộp {n_count} thực thể thành 1 (`{active_prev.get('canonical_name', '')}`)",
                type="primary",
                disabled=not active_prev.get("valid", False),
                width='stretch',
                key="btn_apply_entity_merge",
            ):
                try:
                    res = execute_entity_merge_apply(project, collapse_edges=cb_manual_ent_collapse)
                    bump_sync_nonce(collapse_nonce_key)
                    dup_msg = f" Đã hợp nhất {res.merged_duplicate_edges} cạnh trùng bộ ba." if getattr(res, "merged_duplicate_edges", 0) > 0 else ""
                    gaz_msg = _format_gazetteer_merge_notice(project)
                    done_msg = (
                        f"Đã gộp thành công {res.applied_count} thực thể về `{chosen_keep}` · "
                        f"Cạnh duy nhất cập nhật: {len(res.affected_edge_ids)} (Số đầu mút đổi: {res.changed_endpoint_count}).{dup_msg}{gaz_msg}"
                    )
                    m_state.setdefault("flash_messages", []).append(done_msg)
                    if gaz_msg:
                        st.toast("📚 Đã thêm bí danh vào Từ điển Dự án!")
                    st.success(done_msg)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _render_entity_merge_history_section(project: dict, client: FrontendClient) -> None:
    """Phần 3: Lịch sử gộp thực thể, bảng node_redirects và khôi phục snapshot."""
    merges = list(reversed(project.get("entity_merges", [])))
    redirects = project.get("node_redirects", {})
    with st.expander(f"📜 Lịch sử Gộp Thực thể ({len(merges)} phiên) & Bảng Chuyển hướng ID ({len(redirects)} ID cũ)", expanded=False):
        if redirects:
            st.caption("Bảng ánh xạ phẳng `node_redirects` (`old_node_id -> canonical_node_id`):")
            st.json(redirects)
        if not merges:
            st.info("Chưa có phiên gộp thực thể nào trong dự án.")
        else:
            st.dataframe(
                [
                    {
                        "Mã phiên": m.get("merge_id", ""),
                        "Thời điểm": m.get("at", ""),
                        "Giữ lại ID": m.get("keep_id", ""),
                        "Gộp các ID": ", ".join(m.get("drop_ids", [])),
                        "Tên chuẩn": m.get("canonical_name", ""),
                        "Loại chuẩn": m.get("canonical_kind", ""),
                        "Cạnh duy nhất đổi": m.get("affected_edge_count", 0),
                        "Đầu mút đổi": m.get("changed_endpoint_count", 0),
                    }
                    for m in merges
                ],
                width='stretch',
                hide_index=True,
            )
            latest_snap = str(merges[0].get("snapshot_path") or "")
            if latest_snap and Path(latest_snap).exists():
                confirm_undo = st.checkbox(
                    f"Tôi xác nhận khôi phục toàn dự án về snapshot ngay trước phiên gộp `{merges[0].get('merge_id', '')}`",
                    key="chk_restore_entity_merge_snap",
                )
                if st.button(
                    "⏪ Khôi phục toàn dự án về Snapshot trước phiên gộp này",
                    disabled=not confirm_undo,
                    key="btn_restore_entity_merge_snap",
                ):
                    client.restore_snapshot(project, latest_snap)
                    st.session_state["chk_restore_entity_merge_snap"] = False
                    reset_edc_state_if_project_changed(project, force=True)
                    reset_curation_state_if_project_changed(project, force=True)
                    st.success("Đã khôi phục dự án về snapshot trước khi gộp thực thể.")
                    st.rerun()


def render_entity_merge_tab(
    project: dict,
    client: FrontendClient,
    m_state: dict[str, Any],
    nodes: list[dict],
    nodes_by_id: dict[str, dict],
    degrees: dict[str, dict[str, int]],
) -> None:
    """Nội dung Tab 1: Phát hiện nghi trùng, Chọn nhiều & Gộp thực thể số lượng lớn, Bàn gộp 3 bước."""
    for flash_msg in list(m_state.get("flash_messages", [])):
        st.success(flash_msg)
    m_state["flash_messages"] = []

    _render_bulk_duplicate_entity_section(project, client, m_state, nodes_by_id)
    st.divider()
    _render_three_step_entity_workbench(project, m_state, nodes, nodes_by_id, degrees)
    _render_entity_merge_history_section(project, client)


__all__ = [
    "_format_gazetteer_merge_notice",
    "build_entity_merge_preview",
    "execute_entity_merge_apply",
    "render_entity_merge_tab",
]
