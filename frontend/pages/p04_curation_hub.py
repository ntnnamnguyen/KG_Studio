"""Màn hình 04 & 05: Trung tâm Kiểm duyệt & Chuẩn hóa Tri thức Hợp nhất (Knowledge Curation & Alignment Hub).

Tích hợp 3 phân khu nghiệp vụ trong một quy trình thống nhất:
1. Phân khu 1: Chuẩn hóa Lược đồ (Schema EDC - Loại thực thể & Quan hệ do LLM đề xuất).
2. Phân khu 2: Kiểm duyệt Quan hệ & Bằng chứng (Edge curation & evidence inspection).
3. Phân khu 3: Quản lý Hồ sơ Thực thể & Gộp thực thể trùng lặp (Entity merge & resolution).
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.facade import get_facade
from frontend.components.curation_table import (
    render_edge_curation_table_and_batch_bar,
    render_entity_table,
)
from frontend.components.edc_bulk_actions import render_edc_bulk_actions
from frontend.components.edc_review_table import render_edc_review_table
from frontend.components.entity_merge_panel import render_entity_merge_panel
from frontend.components.evidence_panel import (
    render_edge_evidence_and_inspector_panel,
    render_entity_profile_inspector,
)
from frontend.components.pipeline_banner import render_step_next_action
from frontend.components.shared_curation_ui import (
    render_decision_batch_history,
    render_sqlite_resync_banner,
)
from frontend.state.session import (
    get_active_curation_section,
    navigate_to_step,
    reset_curation_state_if_project_changed,
    reset_edc_state_if_project_changed,
    return_to_curation_from_edc,
    set_active_curation_section,
)


def compute_edc_overview_counts(project: dict) -> dict[str, Any]:
    """Tổng hợp số liệu tổng quan đề xuất EDC theo trạng thái và theo từng bảng."""
    proposals = project.get("schema_proposals", [])
    summary = {
        "total": len(proposals),
        "pending": sum(1 for p in proposals if p.get("status") == "pending"),
        "approved": sum(1 for p in proposals if p.get("status") == "approved"),
        "merged": sum(1 for p in proposals if p.get("status") == "merged"),
        "rejected": sum(1 for p in proposals if p.get("status") == "rejected"),
        "by_kind": {},
    }
    for kind in ("entity_types", "relations"):
        sub = [p for p in proposals if p.get("kind") == kind]
        summary["by_kind"][kind] = {
            "total": len(sub),
            "pending": sum(1 for p in sub if p.get("status") == "pending"),
            "approved": sum(1 for p in sub if p.get("status") == "approved"),
            "merged": sum(1 for p in sub if p.get("status") == "merged"),
            "rejected": sum(1 for p in sub if p.get("status") == "rejected"),
        }
    return summary


def compute_curation_overview_counts(project: dict) -> dict[str, int]:
    """Tổng hợp số liệu kiểm duyệt đồ thị (quan hệ, thực thể, trùng lặp)."""
    facade = get_facade()
    return facade.review_stats(project)


def render_curation_hub_page(project: dict, default_tab: str = "schema") -> None:
    """Hiển thị Trung tâm Kiểm duyệt & Chuẩn hóa Tri thức Hợp nhất."""
    facade = get_facade()

    reset_edc_state_if_project_changed(project)
    reset_curation_state_if_project_changed(project)
    model_fp = facade._current_model_fingerprint(project)

    st.subheader("🎯 4. Rà soát & Chuẩn hóa Tri thức (Knowledge Curation Hub)")
    render_step_next_action("review", project)

    st.caption(
        "Quy trình toàn diện làm sạch tri thức trước khi xuất đồ thị: "
        "Chuẩn hóa danh mục lược đồ $\\rightarrow$ Duyệt quan hệ & bằng chứng $\\rightarrow$ Quản lý & gộp thực thể."
    )

    # 1. CẢNH BÁO ĐỒNG BỘ SQLITE DÙNG CHUNG
    render_sqlite_resync_banner(project, key_prefix="hub")

    # 2. KHUNG ĐIỀU HƯỚNG QUAY LẠI KHI CẠNH BỊ VƯỚNG DANH MỤC
    ret_ctx = st.session_state.get("_curation_return_context")
    if isinstance(ret_ctx, dict) and ret_ctx.get("project_id") == str(project.get("project_id") or project.get("name")):
        with st.container(border=True):
            rc1, rc2 = st.columns([3.5, 1.2])
            target_desc = (
                f"cạnh `{ret_ctx.get('edge_id')}`"
                if ret_ctx.get("edge_id")
                else (f"thực thể `{ret_ctx.get('node_id')}`" if ret_ctx.get("node_id") else "phân khu đang mở")
            )
            rc1.info(
                f"🔗 Bạn vừa chuyển từ **Phân khu Quan hệ** sang để xử lý đề xuất EDC `{ret_ctx.get('proposal_id', '')}` "
                f"đang chặn {target_desc}."
            )
            if rc2.button("↩️ Quay lại mục đang kiểm duyệt ở Phân khu Quan hệ", width='stretch', key="btn_hub_return_curation"):
                return_to_curation_from_edc(project)
                st.session_state["curation_hub_active_tab"] = "edges"
                st.rerun()

    # 3. BẢNG CHỈ SỐ SỨC KHỎE ĐỒ THỊ & LƯỢC ĐỒ TỔNG THỂ (Unified Dashboard Metrics)
    edc_counts = compute_edc_overview_counts(project)
    cur_stats = compute_curation_overview_counts(project)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("📐 Lược đồ chờ duyệt", edc_counts["pending"], help="Đề xuất loại thực thể hoặc quan hệ mới cần chuẩn hóa")
    m2.metric("🔬 Quan hệ chờ duyệt", cur_stats["pending"], help="Các cạnh quan hệ cụ thể trích xuất từ tài liệu đang chờ duyệt")
    m3.metric("⚠️ Cần kiểm tra", cur_stats["check"], help="Các cạnh bị LLM hoặc quy tắc đánh dấu nghi ngờ")
    m4.metric("⛔ Vướng danh mục", cur_stats["schema_blocked"], help="Các cạnh có quan hệ/loại thực thể chưa được duyệt ở Phân khu 1")
    dup_val = cur_stats.get("duplicate_pairs", -1)
    dup_label = f"{dup_val}" if dup_val >= 0 else "Chưa quét"
    m5.metric("🔀 Cặp nghi trùng", dup_label, help="Số cặp thực thể nghi trùng lặp. Được tính theo yêu cầu ở Phân khu 3.")
    m6.metric("📊 Đồ thị (Node / Edge)", f"{cur_stats['nodes']} / {cur_stats['edges']}", help="Tổng số thực thể và quan hệ hiện có")

    # Phím tắt hành động nhanh trực tiếp từ số liệu (Action Cards)
    act_col1, act_col2, act_col3 = st.columns(3)
    with act_col1:
        if cur_stats["schema_blocked"] > 0 or edc_counts["pending"] > 0:
            if st.button(
                f"⛔ Xử lý {edc_counts['pending']} Lược đồ & {cur_stats['schema_blocked']} cạnh vướng",
                width="stretch",
                key="btn_act_goto_schema",
                type="primary" if cur_stats["schema_blocked"] > 0 else "secondary",
                help="Chuyển ngay sang Phân khu 1: Chuẩn hóa Lược đồ",
            ):
                st.session_state["curation_hub_active_tab"] = "schema"
                st.rerun()
    with act_col2:
        if cur_stats["pending"] > 0 or cur_stats["check"] > 0:
            if st.button(
                f"🔬 Rà soát {cur_stats['pending']} Quan hệ chờ duyệt",
                width="stretch",
                key="btn_act_goto_edges",
                type="primary" if cur_stats["pending"] > 0 and cur_stats["schema_blocked"] == 0 else "secondary",
                help="Chuyển ngay sang Phân khu 2: Duyệt Quan hệ & Bằng chứng",
            ):
                st.session_state["curation_hub_active_tab"] = "edges"
                st.rerun()
    with act_col3:
        if dup_val > 0:
            if st.button(
                f"🔀 Khử trùng lặp {dup_val} Cặp thực thể nghi trùng",
                width="stretch",
                key="btn_act_goto_entities_merge",
                type="primary",
                help="Chuyển ngay sang Phân khu 3: Công cụ Gộp Thực thể",
            ):
                st.session_state["curation_hub_active_tab"] = "entities"
                st.session_state["hub_entity_submode_radio"] = "🔀 Công cụ Gộp Thực thể Trùng lặp (Entity Merge)"
                st.rerun()
        else:
            if st.button(
                f"🏛️ Xem {cur_stats['nodes']} Hồ sơ thực thể",
                width="stretch",
                key="btn_act_goto_entities_list",
                help="Chuyển ngay sang Phân khu 3: Quản lý Hồ sơ Thực thể",
            ):
                st.session_state["curation_hub_active_tab"] = "entities"
                st.rerun()

    st.divider()

    # 4. THANH CHUYỂN PHÂN KHU NGHIỆP VỤ (Sub-navigation)
    hub_tabs = {
        "schema": "📐 1. Chuẩn hóa Lược đồ (Schema EDC)",
        "edges": "🔬 2. Duyệt Quan hệ & Bằng chứng",
        "entities": "🏛️ 3. Quản lý & Gộp thực thể",
    }
    hub_tab_keys = list(hub_tabs.keys())

    # Khởi tạo hoặc cập nhật phân khu hiện hành
    if "curation_hub_active_tab" not in st.session_state:
        st.session_state["curation_hub_active_tab"] = default_tab
    elif st.session_state.get("_hub_request_tab"):
        st.session_state["curation_hub_active_tab"] = st.session_state.pop("_hub_request_tab")

    current_active_tab = st.session_state.get("curation_hub_active_tab", default_tab)
    if current_active_tab not in hub_tab_keys:
        current_active_tab = default_tab

    selected_tab = st.radio(
        "Chọn phân khu làm việc trong Hub Kiểm duyệt:",
        hub_tab_keys,
        index=hub_tab_keys.index(current_active_tab),
        format_func=lambda k: hub_tabs[k],
        horizontal=True,
        key="curation_hub_radio_subtab",
    )
    if selected_tab != current_active_tab:
        st.session_state["curation_hub_active_tab"] = selected_tab
        st.rerun()

    st.divider()

    # 5. NỘI DUNG TỪNG PHÂN KHU
    if selected_tab == "schema":
        # =========================================================================
        # PHÂN KHU 1: CHUẨN HÓA LƯỢC ĐỒ (SCHEMA EDC)
        # =========================================================================
        st.markdown("#### 📐 Phân khu 1: Chuẩn hóa Lược đồ & Đề xuất Danh mục (Schema EDC)")
        st.caption(
            "Phân định rõ ràng: Đây là nơi chuẩn hóa **LOẠI THỰC THỂ** (`entity_types`) và **LOẠI QUAN HỆ** (`relations`) "
            "do LLM đề xuất vào danh mục chính thức. Thao tác gộp các thực thể cụ thể (node) được thực hiện ở **Phân khu 3**."
        )

        # Khu vực A: Loại thực thể
        with st.container(border=True):
            st.info(
                "💡 **Khu vực A - Đề xuất Loại thực thể (Entity Types):** "
                "Ví dụ: `Chứng nhận di sản`, `Di tích lịch sử`, `Nhân vật`. "
                "Các thực thể cụ thể thuộc loại này (ví dụ: *Văn Miếu*, *Chùa Một Cột*) nằm ở Phân khu 2 và 3."
            )
            ctx_a = render_edc_review_table(
                project,
                "entity_types",
                "A. Đề xuất loại thực thể (`entity_types`)",
                current_model_fingerprint=model_fp,
            )
            render_edc_bulk_actions(
                project,
                "entity_types",
                selected_ids=ctx_a["selected_ids"],
                eligible_filtered=ctx_a["eligible_filtered"],
                filtered_proposals=ctx_a["filtered_proposals"],
                current_model_fingerprint=model_fp,
            )

        st.divider()

        # Khu vực B: Quan hệ
        with st.container(border=True):
            ctx_b = render_edc_review_table(
                project,
                "relations",
                "B. Đề xuất quan hệ (`relations`)",
                current_model_fingerprint=model_fp,
            )
            render_edc_bulk_actions(
                project,
                "relations",
                selected_ids=ctx_b["selected_ids"],
                eligible_filtered=ctx_b["eligible_filtered"],
                filtered_proposals=ctx_b["filtered_proposals"],
                current_model_fingerprint=model_fp,
            )

        st.divider()

        # Khu vực C: Công cụ Auto Target Alignment
        cfg = facade.get_edc_plus_r_settings(project)
        with st.expander("🤖 Công cụ Chuẩn hóa Tự động (Auto Target Alignment — Không tính là nhãn con người)"):
            st.caption(
                f"Chính sách: Tự động gán `merged` (`auto_aligned=True`) nếu điểm tương đồng ≥ `{cfg.auto_align_threshold:.2f}`; "
                f"gợi ý ứng viên nếu điểm ≥ `{cfg.candidate_threshold:.2f}`."
            )
            ac1, ac2 = st.columns(2)
            sel_types = ctx_a["selected_ids"]
            sel_rels = ctx_b["selected_ids"]
            if ac1.button(
                f"🤖 Chạy chuẩn hóa tự động cho {len(sel_types)} Loại thực thể đã chọn",
                disabled=len(sel_types) == 0,
                width='stretch',
                key="btn_hub_auto_align_types",
            ):
                facade.create_snapshot(project)
                summary = facade.run_target_alignment_on_pending(project, proposal_ids=sel_types, kind="entity_types")
                facade.save_project(project)
                st.success(
                    f"Chuẩn hóa tự động (Loại thực thể): Hợp nhất {summary['auto_aligned']} mục, "
                    f"Gợi ý {summary['suggested_for_review']} mục, Lỗi {summary.get('error_count', 0)} mục."
                )
                st.rerun()

            if ac2.button(
                f"🤖 Chạy chuẩn hóa tự động cho {len(sel_rels)} Quan hệ đã chọn",
                disabled=len(sel_rels) == 0,
                width='stretch',
                key="btn_hub_auto_align_rels",
            ):
                facade.create_snapshot(project)
                summary = facade.run_target_alignment_on_pending(project, proposal_ids=sel_rels, kind="relations")
                facade.save_project(project)
                st.success(
                    f"Chuẩn hóa tự động (Quan hệ): Hợp nhất {summary['auto_aligned']} mục, "
                    f"Gợi ý {summary['suggested_for_review']} mục, Lỗi {summary.get('error_count', 0)} mục."
                )
                st.rerun()

        # Lịch sử lô quyết định lược đồ dùng chung component
        render_decision_batch_history(
            project,
            batch_key="schema_decision_batches",
            title="Lịch sử Lô Quyết định Lược đồ & Khôi phục Snapshot",
            on_restore_callbacks=[reset_edc_state_if_project_changed],
            key_prefix="hub_schema_batch",
            enable_jump_to_proposal=True,
        )

    elif selected_tab == "edges":
        # =========================================================================
        # PHÂN KHU 2: KIỂM DUYỆT QUAN HỆ & BẰNG CHỨNG
        # =========================================================================
        st.markdown("#### 🔬 Phân khu 2: Kiểm duyệt Quan hệ Tri thức & Bằng chứng Văn bản")
        st.caption(
            "Cổng kiểm tra chất lượng đồ thị: Xác thực các bộ ba (Source - Relation - Target) và trích đoạn văn bản chứng minh. "
            "Nếu quan hệ bị gắn cờ `Vướng danh mục`, hãy chuyển sang Phân khu 1 để chuẩn hóa nhãn quan hệ."
        )

        table_ctx = render_edge_curation_table_and_batch_bar(project)
        st.divider()
        render_edge_evidence_and_inspector_panel(project, table_ctx.get("focused_edge_id", ""))

        st.divider()
        render_decision_batch_history(
            project,
            batch_key="curation_decision_batches",
            title="Lịch sử Lô Kiểm duyệt Quan hệ & Khôi phục Snapshot",
            on_restore_callbacks=[reset_edc_state_if_project_changed, reset_curation_state_if_project_changed],
            key_prefix="hub_edge_batch",
        )

    elif selected_tab == "entities":
        # =========================================================================
        # PHÂN KHU 3: QUẢN LÝ HỒ SƠ THỰC THỂ & GỘP THỰC THỂ TRÙNG LẶP
        # =========================================================================
        st.markdown("#### 🏛️ Phân khu 3: Quản lý Hồ sơ Thực thể & Gộp Thực thể Trùng lặp (Entity Resolution)")
        st.caption(
            "Quản lý danh sách các thực thể cụ thể (node), tra cứu bậc liên kết, và gộp các thực thể đồng nghĩa/trùng tên "
            "về một thực thể đại diện duy nhất (canonical entity) kèm chuyển hướng cạnh tự động."
        )

        ent_subnav = st.radio(
            "Chế độ hiển thị Phân khu 3:",
            ["🏛️ Bảng Hồ sơ Thực thể & Trọng số", "🔀 Công cụ Gộp Thực thể Trùng lặp (Entity Merge)"],
            horizontal=True,
            key="hub_entity_submode_radio",
        )

        if ent_subnav.startswith("🏛️"):
            ent_ctx = render_entity_table(project)
            st.divider()
            render_entity_profile_inspector(project, ent_ctx.get("focused_node_id", ""))
        else:
            render_entity_merge_panel(project)

        st.divider()
        render_decision_batch_history(
            project,
            batch_key="curation_decision_batches",
            title="Lịch sử Lô Thao tác Thực thể & Khôi phục Snapshot",
            on_restore_callbacks=[reset_edc_state_if_project_changed, reset_curation_state_if_project_changed],
            key_prefix="hub_entity_batch",
        )

    # 6. ĐIỀU HƯỚNG SANG BƯỚC TIẾP THEO
    st.divider()
    with st.container(border=True):
        col_msg, col_btn = st.columns([3.5, 1.5])
        col_msg.markdown(
            "➡️ **Hoàn tất rà soát?** "
            "Chuyển sang Bước 5 để trực quan hóa đồ thị tri thức, kiểm tra tính toàn vẹn, xuất file JSON/ZIP hoặc đồng bộ lên Neo4j."
        )
        if col_btn.button("➡️ Chuyển sang Bước 5: Khai thác & Xuất đồ thị", type="primary", width="stretch", key="p04_btn_goto_explore"):
            navigate_to_step("explore")
            st.rerun()


