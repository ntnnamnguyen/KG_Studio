"""Tab 1: Bàn gộp thực thể theo quy trình 3 bước, phát hiện nghi trùng và gộp hàng loạt."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows, compute_project_revision
from backend.domain.curation.service import duplicate_suggestions
from frontend.client import FrontendClient, get_client
from frontend.components.merge.provenance_view import render_entity_provenance_panel
from frontend.state.session import (
    get_curation_section_state,
    reset_curation_state_if_project_changed,
    reset_edc_state_if_project_changed,
    stage_entities_for_merge,
    store_entity_merge_preview,
    update_merge_draft,
)
from shared.schemas.curation import (
    CurationResultDTO,
    EntityMergePreviewDTO,
    EntityMergeRequestDTO,
)
from shared.text_utils import normal, uid


def build_entity_merge_preview(
    project: dict,
    *,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> EntityMergePreviewDTO:
    """Tạo bản xem trước tác động gộp thực thể từ trạng thái bàn gộp hiện tại và lưu vào session."""
    svc_client = client or get_client()
    m_state = get_curation_section_state(project, "merge", state_store)
    req_id = uid()
    req = EntityMergeRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        member_ids=list(m_state.get("member_ids") or []),
        keep_id=str(m_state.get("keep_id") or ""),
        canonical_name=str(m_state.get("canonical_name") or ""),
        canonical_kind=str(m_state.get("canonical_kind") or ""),
        kind_resolution_note=str(m_state.get("kind_resolution_note") or ""),
        canonical_description=str(m_state.get("canonical_description") or ""),
        alias_overrides=m_state.get("alias_overrides"),
        note=str(m_state.get("note") or ""),
        expected_revision=compute_project_revision(project),
        request_id=req_id,
    )
    preview = svc_client.preview_entity_merge(project, req)
    store_entity_merge_preview(project, preview, request_id=req_id, state_store=state_store)
    return preview


def execute_entity_merge_apply(
    project: dict,
    *,
    collapse_edges: bool = True,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> CurationResultDTO:
    """Thực thi gộp thực thể sau khi đã xem trước hợp lệ và làm sạch bàn gộp."""
    svc_client = client or get_client()
    m_state = get_curation_section_state(project, "merge", state_store)
    active_prev = m_state.get("active_preview")
    if not active_prev:
        raise ValueError("Vui lòng chạy Xem trước tác động gộp trước khi xác nhận gộp thực thể.")

    raw_aliases = list(m_state.get("alias_overrides") or m_state.get("aliases") or [])
    req = EntityMergeRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        member_ids=list(active_prev.get("member_ids") or m_state.get("member_ids") or []),
        keep_id=str(active_prev.get("keep_id") or m_state.get("keep_id") or ""),
        canonical_name=str(active_prev.get("canonical_name") or m_state.get("canonical_name") or ""),
        canonical_kind=str(active_prev.get("canonical_kind") or m_state.get("canonical_kind") or ""),
        kind_resolution_note=str(m_state.get("kind_resolution_note") or ""),
        canonical_description=str(active_prev.get("canonical_description") or m_state.get("canonical_description") or ""),
        aliases=raw_aliases,
        note=str(m_state.get("note") or ""),
        expected_revision=str(active_prev.get("revision") or compute_project_revision(project)),
        request_id=str(m_state.get("preview_request_id") or uid()),
        collapse_edges=collapse_edges,
    )
    result = svc_client.apply_entity_merge(project, req, preview=active_prev)
    # Sau khi gộp xong: giữ lại duy nhất thực thể đích trên bàn hoặc làm rỗng danh sách chờ gộp
    m_state["member_ids"] = []
    m_state["keep_id"] = ""
    m_state["active_preview"] = None
    m_state["preview_request_id"] = ""
    m_state["last_result"] = result.to_dict()
    return result


def render_entity_merge_tab(
    project: dict,
    client: FrontendClient,
    m_state: dict[str, Any],
    nodes: list[dict],
    nodes_by_id: dict[str, dict],
    degrees: dict[str, dict[str, int]],
) -> None:
    """Nội dung Tab 1: Phát hiện nghi trùng, Chọn nhiều & Gộp thực thể số lượng lớn, Bàn gộp 3 bước."""
    # --- PHẦN 1: DANH SÁCH CẶP THỰC THỂ NGHI TRÙNG & GỘP HÀNG LOẠT ---
    with st.container(border=True):
        st.markdown("#### 🔍 1. Ứng viên Thực thể Nghi trùng & Gộp Hàng loạt (Bulk Entity Merge)")
        st.caption(
            "Hệ thống phát hiện các cặp thực thể trùng tên chuẩn hóa, giao nhau tên/bí danh hoặc gần giống chuỗi. "
            "Hỗ trợ **chọn nhiều và gộp hàng loạt** an toàn theo thuật toán cụm liên thông (DSU) bảo toàn bậc kết nối."
        )
        sc1, sc2 = st.columns([1.6, 2.4])
        fuzzy_val = sc1.slider(
            "Ngưỡng tương đồng tên thực thể (Fuzzy threshold)",
            min_value=0.0,
            max_value=0.98,
            value=float(m_state.get("fuzzy_threshold", 0.82)),
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

        # Tự động dọn sạch các lựa chọn cũ hoặc không hợp lệ khỏi session_state
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
            # Các nút thao tác chọn nhanh
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

            # Đồng bộ lại lựa chọn từ checkbox
            new_selected = {r["pair_key"] for r in edited_cands if r.get("Chọn")}
            if new_selected != cur_selected:
                st.session_state[sel_cand_pairs_key] = new_selected
                st.rerun()

            # Thao tác nhanh cho các cặp đang chọn
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
                    cb_bulk_ent_collapse = st.checkbox(
                        "Tự động hợp nhất các cạnh trùng bộ ba (dồn bằng chứng đầy đủ)",
                        value=False,
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
                            st.success(
                                f"Đã gộp thành công {res.applied_count} thực thể trong {len(selected_pairs_to_merge)} cặp đã chọn. "
                                f"Cập nhật {len(res.affected_edge_ids)} cạnh (Đổi {res.changed_endpoint_count} đầu mút).{dup_msg}"
                            )
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

    st.divider()

    # --- PHẦN 2: BÀN GỘP THỰC THỂ 3 BƯỚC (Mục 7.2 & 7.3) ---
    with st.container(border=True):
        st.markdown("#### 🔀 2. Bàn Gộp Thực thể theo Quy trình 3 Bước (Hỗ trợ gộp 2..N thực thể tùy biến)")

        # BƯỚC 1: CHỌN VÀ SO SÁNH THỰC THỂ CẠNH NHAU
        st.markdown("##### Bước 1 — Chọn và so sánh các thực thể cần gộp")
        all_node_ids = [str(n["id"]) for n in nodes if n.get("id")]
        cur_members = [nid for nid in m_state.get("member_ids", []) if nid in nodes_by_id]
        selected_members = st.multiselect(
            "Chọn từ 2 thực thể trở lên để so sánh và gộp thành 1 thực thể duy nhất",
            all_node_ids,
            default=cur_members,
            format_func=lambda nid: (
                f"{nodes_by_id[nid].get('name', nid)} [{nodes_by_id[nid].get('kind', '?')}] "
                f"(Bậc: {degrees.get(nid, {'total': 0})['total']} · ID: {nid})"
            ),
            key="merge_multiselect_members",
        )
        if selected_members != cur_members:
            m_state["member_ids"] = []
            stage_entities_for_merge(project, selected_members, switch_to_merge=False)
            st.rerun()

        if len(selected_members) < 2:
            st.info("Hãy chọn ít nhất **2 thực thể** (từ bảng gợi ý ở trên hoặc từ ô tìm kiếm) để bắt đầu so sánh và gộp.")
        else:
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

            # BƯỚC 2: GIẢI QUYẾT XUNG ĐỘT TRƯỜNG DỮ LIỆU
            st.markdown("##### Bước 2 — Giải quyết xung đột trường dữ liệu & Chọn hồ sơ chuẩn")
            distinct_kinds = list(dict.fromkeys(str(n.get("kind") or "").strip() for n in member_nodes if n.get("kind")))
            has_kind_conflict = len({normal(k) for k in distinct_kinds if k}) > 1

            approved_types = [str(t["name"]) for t in catalog_rows(project, "entity_types")]
            for k in distinct_kinds:
                if k and k not in approved_types:
                    approved_types.insert(0, k)

            c_keep, c_name, c_kind = st.columns(3)
            cur_keep = str(m_state.get("keep_id") or selected_members[0])
            if cur_keep not in selected_members:
                cur_keep = selected_members[0]
            chosen_keep = c_keep.selectbox(
                "Thực thể đích giữ lại ID (`keep_id`)",
                selected_members,
                index=selected_members.index(cur_keep),
                format_func=lambda nid: f"{nodes_by_id[nid].get('name', nid)} ({nid})",
                key="merge_keep_id_select",
            )

            name_suggestions = list(dict.fromkeys(str(n.get("name", "")) for n in member_nodes if n.get("name")))
            cur_canon_name = str(m_state.get("canonical_name") or nodes_by_id[chosen_keep].get("name", ""))
            chosen_name = c_name.text_input(
                f"Tên chuẩn hiển thị (Gợi ý: {', '.join(name_suggestions[:3])})",
                value=cur_canon_name,
                key="merge_canon_name_input",
            )

            cur_canon_kind = str(m_state.get("canonical_kind") or nodes_by_id[chosen_keep].get("kind", ""))
            chosen_kind = c_kind.selectbox(
                "Loại thực thể chuẩn sau khi gộp",
                approved_types if approved_types else [""],
                index=approved_types.index(cur_canon_kind) if cur_canon_kind in approved_types else 0,
                key="merge_canon_kind_select",
            )

            kind_note = str(m_state.get("kind_resolution_note") or "")
            if has_kind_conflict:
                st.warning(
                    f"⚠️ **Xung đột loại thực thể:** Các thực thể đang chọn có loại khác nhau ({', '.join(distinct_kinds)}). "
                    "Bắt buộc nhập lý do chọn loại chuẩn; các cạnh nối với thực thể đổi loại sẽ chuyển về **Cần kiểm tra**."
                )
                kind_note = st.text_input(
                    "Lý do giải quyết xung đột loại thực thể (bắt buộc khi gộp thực thể khác loại)",
                    value=kind_note,
                    key="merge_kind_note_input",
                )

            chosen_desc = st.text_area(
                "Mô tả tổng hợp sau khi gộp",
                value=str(m_state.get("canonical_description") or ""),
                height=80,
                key="merge_canon_desc_input",
            )
            merge_note = st.text_input(
                "Ghi chú phiên gộp thực thể",
                value=str(m_state.get("note") or ""),
                key="merge_note_input",
            )

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

            # BƯỚC 3: XEM TRƯỚC TÁC ĐỘNG & XÁC NHẬN GỘP
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

                st.caption(
                    f"Bí danh sẽ được bảo toàn tự động: `{'; '.join(active_prev.get('merged_aliases', [])) or '(Không có)'}` · "
                    "Toàn bộ ID cạnh và bằng chứng được giữ nguyên 100% (không tự xóa ngầm bất kỳ cạnh nào)."
                )

                n_count = len(active_prev.get("member_ids", []))
                cb_manual_ent_collapse = st.checkbox(
                    "Tự động hợp nhất các cạnh trùng bộ ba (dồn bằng chứng đầy đủ)",
                    value=False,
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
                        dup_msg = f" Đã hợp nhất {res.merged_duplicate_edges} cạnh trùng bộ ba." if getattr(res, "merged_duplicate_edges", 0) > 0 else ""
                        st.success(
                            f"Đã gộp thành công {res.applied_count} thực thể về `{chosen_keep}` · "
                            f"Cạnh duy nhất cập nhật: {len(res.affected_edge_ids)} (Số đầu mút đổi: {res.changed_endpoint_count}).{dup_msg}"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    # --- PHẦN 3: LỊCH SỬ GỘP THỰC THỂ & BẢNG CHUYỂN HƯỚNG ID (node_redirects) ---
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
                    reset_edc_state_if_project_changed(project)
                    reset_curation_state_if_project_changed(project)
                    st.success("Đã khôi phục dự án về snapshot trước khi gộp thực thể.")
                    st.rerun()
