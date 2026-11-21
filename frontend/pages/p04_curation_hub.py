"""Màn hình 04 & 05: Trung tâm Kiểm duyệt & Chuẩn hóa Tri thức Hợp nhất (Knowledge Curation & Alignment Hub).

Tích hợp quy trình làm sạch đồ thị tuyến tính 3 bước không chồng chéo:
1. Bước 1: Chuẩn hóa Nhãn Lược đồ (Schema EDC & Target Alignment + Công cụ gom cụm bổ sung cho EDC mở).
2. Bước 2: Gộp Thực thể Trùng lặp & Quản lý Hồ sơ Bí danh (Entity Merge & Domain Gazetteer).
3. Bước 3: Khử Cạnh Lặp theo Bộ ba & Duyệt Bằng chứng Văn bản (Triple Deduplication & Edge Curation).
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.domain.curation.service import compute_apparent_duplicate_edge_groups
from backend.facade import get_facade
from frontend.client import get_client
from frontend.components.curation_table import (
    render_edge_curation_table_and_batch_bar,
    render_entity_table,
)
from frontend.components.edc_bulk_actions import render_edc_bulk_actions
from frontend.components.edc_review_table import render_edc_review_table
from frontend.components.entity_merge_panel import (
    render_entity_merge_history_body,
    render_entity_merge_panel,
    render_entity_type_merge_tab,
    render_relation_merge_tab,
    render_triple_dedup_history_body,
    render_triple_dedup_tab,
)
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
    bump_sync_nonce,
    get_active_curation_section,
    get_curation_section_state,
    get_session_llm_params,
    navigate_to_step,
    reset_curation_state_if_project_changed,
    reset_edc_state_if_project_changed,
    return_to_curation_from_edc,
    sync_keyed_choice,
    sync_keyed_value,
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
        "Quy trình tuyến tính 3 bước làm sạch đồ thị không chồng chéo: "
        "**Bước 1:** Chuẩn hóa nhãn lược đồ (Schema EDC) $\\rightarrow$ "
        "**Bước 2:** Gộp thực thể trùng & làm giàu từ điển bí danh $\\rightarrow$ "
        "**Bước 3:** Khử cạnh lặp theo bộ ba & duyệt bằng chứng nguyên văn."
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
                f"🔗 Bạn vừa chuyển sang **Bước 1 (Chuẩn hóa Lược đồ)** để xử lý đề xuất EDC `{ret_ctx.get('proposal_id', '')}` "
                f"đang chặn {target_desc}."
            )
            if rc2.button("↩️ Quay lại mục đang kiểm duyệt", width='stretch', key="btn_hub_return_curation"):
                return_to_curation_from_edc(project)
                st.rerun()

    # 3. BẢNG CHỈ SỐ SỨC KHỎE ĐỒ THỊ & LƯỢC ĐỒ TỔNG THỂ (Unified Dashboard Metrics)
    edc_counts = compute_edc_overview_counts(project)
    cur_stats = compute_curation_overview_counts(project)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("📐 1. Lược đồ chờ duyệt", edc_counts["pending"], help="Đề xuất loại thực thể hoặc quan hệ mới cần chuẩn hóa ở Bước 1")
    m2.metric("⛔ Vướng danh mục", cur_stats["schema_blocked"], help="Các cạnh có quan hệ/loại thực thể chưa được duyệt ở Bước 1")
    dup_val = cur_stats.get("duplicate_pairs", -1)
    dup_label = f"{dup_val}" if dup_val >= 0 else "Chưa quét"
    m3.metric("🔀 2. Cặp thực thể nghi trùng", dup_label, help="Số cặp thực thể nghi trùng lặp cần gộp ở Bước 2.")
    m4.metric("🔬 3. Quan hệ chờ duyệt", cur_stats["pending"], help="Các cạnh quan hệ cụ thể trích xuất từ tài liệu đang chờ duyệt ở Bước 3")
    m5.metric("⚠️ Cần kiểm tra", cur_stats["check"], help="Các cạnh bị quy tắc toàn vẹn hoặc tự nối đánh dấu cần kiểm tra ở Bước 3")
    m6.metric("📊 Đồ thị (Node / Edge)", f"{cur_stats['nodes']} / {cur_stats['edges']}", help="Tổng số thực thể và quan hệ hiện có")

    # 4. THANH CHUYỂN QUY TRÌNH KIỂM DUYỆT TUYẾN TÍNH 3 BƯỚC DUY NHẤT (Sub-navigation)
    hub_tabs = {
        "schema": "📐 Bước 1: Chuẩn hóa Lược đồ (Schema EDC)",
        "entities": "🏛️ Bước 2: Gộp Thực thể & Hồ sơ Bí danh",
        "edges": "🔬 Bước 3: Khử Cạnh Lặp & Duyệt Bằng chứng",
    }
    hub_tab_keys = list(hub_tabs.keys())

    # Khởi tạo hoặc cập nhật phân khu hiện hành
    if "curation_hub_active_tab" not in st.session_state:
        st.session_state["curation_hub_active_tab"] = default_tab
    if st.session_state.get("_hub_request_tab"):
        st.session_state["curation_hub_active_tab"] = st.session_state.pop("_hub_request_tab")
        bump_sync_nonce("_curation_hub_tab_nonce")

    current_active_tab = st.session_state.get("curation_hub_active_tab", default_tab)
    if current_active_tab not in hub_tab_keys:
        current_active_tab = default_tab
        st.session_state["curation_hub_active_tab"] = current_active_tab

    tab_nonce = int(st.session_state.get("_curation_hub_tab_nonce") or 0)
    sync_keyed_choice(
        "curation_hub_radio_subtab",
        hub_tab_keys,
        current_active_tab,
        (current_active_tab, tab_nonce),
    )

    selected_tab = st.radio(
        "Quy trình làm sạch tri thức 3 bước trong Hub Kiểm duyệt:",
        hub_tab_keys,
        format_func=lambda k: hub_tabs[k],
        horizontal=True,
        key="curation_hub_radio_subtab",
    )
    if selected_tab != current_active_tab:
        st.session_state["curation_hub_active_tab"] = selected_tab
        if selected_tab == "edges":
            st.session_state["_curation_active_section"] = "edges"
        elif selected_tab == "entities":
            sub = str(st.session_state.get("_curation_entity_submode") or "")
            st.session_state["_curation_active_section"] = "merge" if sub.startswith("🔀") else "entities"
        bump_sync_nonce("_curation_hub_tab_nonce")
        st.rerun()

    st.divider()

    # 5. NỘI DUNG TỪNG BƯỚC
    if selected_tab == "schema":
        # =========================================================================
        # BƯỚC 1: CHUẨN HÓA LƯỢC ĐỒ (SCHEMA EDC & TARGET ALIGNMENT)
        # =========================================================================
        st.markdown("#### 📐 Bước 1: Chuẩn hóa Nhãn Lược đồ & Đề xuất Danh mục (Schema EDC)")
        st.caption(
            "Ánh xạ **LOẠI THỰC THỂ** (`entity_types`) và **LOẠI QUAN HỆ** (`relations`) do LLM sinh ra về danh mục chuẩn (CIDOC CRM) "
            "bằng bộ chấm điểm đa tín hiệu `TargetAligner` và thẩm định LLM. "
            "Sau khi khóa danh mục lược đồ ở Bước 1, chuyển sang **Bước 2** để gộp các thực thể trùng lặp."
        )

        # Gộp 2 bảng 1A (Loại thực thể) và 1B (Quan hệ) vào 2 tab gọn gàng để tránh trang quá dài
        tab_edc_types, tab_edc_rels = st.tabs([
            "🏷️ 1A. Đề xuất Loại thực thể (`entity_types`)",
            "🔗 1B. Đề xuất Quan hệ (`relations`)",
        ])

        with tab_edc_types:
            st.info(
                "💡 **Bước 1A - Đề xuất Loại thực thể (`entity_types`):** "
                "Ví dụ: `Chứng nhận di sản`, `Di tích lịch sử`, `Nhân vật`. "
                "Các đỉnh thực thể cụ thể (ví dụ: *Văn Miếu*, *Chùa Một Cột*) sẽ được gộp tại **Bước 2**."
            )
            ctx_a = render_edc_review_table(
                project,
                "entity_types",
                "1A. Đề xuất loại thực thể (`entity_types`)",
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

        with tab_edc_rels:
            ctx_b = render_edc_review_table(
                project,
                "relations",
                "1B. Đề xuất quan hệ (`relations`)",
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

        # Bước 1C: Công cụ Auto Target Alignment
        cfg = facade.get_edc_plus_r_settings(project)
        with st.expander("🤖 Bước 1C — Chuẩn hóa Tự động (Auto Target Alignment — Không tính là nhãn con người)"):
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
                try:
                    summary = facade.run_target_alignment_on_pending(
                        project,
                        proposal_ids=sel_types,
                        kind="entity_types",
                        llm_params=get_session_llm_params(),
                    )
                    st.success(
                        f"Chuẩn hóa tự động (Loại thực thể): Hợp nhất {summary['auto_aligned']} mục, "
                        f"Gợi ý {summary['suggested_for_review']} mục, Lỗi {summary.get('error_count', 0)} mục."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi chuẩn hóa tự động loại thực thể: {exc}")

            if ac2.button(
                f"🤖 Chạy chuẩn hóa tự động cho {len(sel_rels)} Quan hệ đã chọn",
                disabled=len(sel_rels) == 0,
                width='stretch',
                key="btn_hub_auto_align_rels",
            ):
                try:
                    summary = facade.run_target_alignment_on_pending(
                        project,
                        proposal_ids=sel_rels,
                        kind="relations",
                        llm_params=get_session_llm_params(),
                    )
                    st.success(
                        f"Chuẩn hóa tự động (Quan hệ): Hợp nhất {summary['auto_aligned']} mục, "
                        f"Gợi ý {summary['suggested_for_review']} mục, Lỗi {summary.get('error_count', 0)} mục."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi chuẩn hóa tự động quan hệ: {exc}")

        # Công cụ bổ sung cho chế độ EDC mở (Gộp Quan hệ & Loại Thực thể hàng loạt)
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        hub_snap_nonce = int(st.session_state.get("_curation_snapshot_nonce") or 0)
        with st.container(border=True):
            sync_keyed_value("cb_hub_show_open_edc_tools", False, (proj_id, "open_edc", hub_snap_nonce))
            show_open_edc_tools = st.checkbox(
                "🛠️ Mở công cụ bổ sung (dành cho chế độ EDC mở không có danh mục đích): Gộp Nhãn Quan hệ & Loại Thực thể hàng loạt",
                key="cb_hub_show_open_edc_tools",
                help=(
                    "Ở chế độ chuẩn EDC+R đã có danh mục đích, Bước 1A–1C phía trên đã đảm nhiệm trọn vẹn việc ánh xạ lược đồ. "
                    "Chỉ cần bật công cụ này khi bạn chạy chế độ EDC mở (không có danh mục đích ban đầu) và muốn gom cụm vị từ/loại thực thể tự do."
                ),
            )
            if show_open_edc_tools:
                st.divider()
                client = get_client()
                m_state = get_curation_section_state(project, "merge")
                open_tab_rel, open_tab_type = st.tabs([
                    "🔗 Gộp Nhãn Quan hệ Hàng loạt (Relation Merge)",
                    "🏷️ Chuẩn hóa Loại Thực thể (Entity Type Merge)",
                ])
                with open_tab_rel:
                    render_relation_merge_tab(project, client, m_state)
                with open_tab_type:
                    render_entity_type_merge_tab(project, client, m_state)

        # Lịch sử lô quyết định lược đồ dùng chung component (duy nhất 1 expander)
        render_decision_batch_history(
            project,
            batch_key="schema_decision_batches",
            title="Lịch sử Lô Quyết định Lược đồ & Khôi phục Snapshot",
            on_restore_callbacks=[lambda p: reset_edc_state_if_project_changed(p, force=True)],
            key_prefix="hub_schema_batch",
            enable_jump_to_proposal=True,
        )

    elif selected_tab == "entities":
        # =========================================================================
        # BƯỚC 2: QUẢN LÝ HỒ SƠ THỰC THỂ & GỘP THỰC THỂ TRÙNG LẶP
        # =========================================================================
        st.markdown("#### 🏛️ Bước 2: Gộp Thực thể Trùng lặp & Quản lý Hồ sơ Bí danh (Entity Resolution)")
        st.caption(
            "Gộp các đỉnh thực thể đồng nghĩa hoặc biến thể tên gọi về một thực thể đại diện duy nhất (Canonical Node) "
            "theo cụm liên thông DSU, tự động chuyển hướng cạnh và **làm giàu Từ điển Bí danh (`domain_gazetteer`)** cho các lần trích xuất sau."
        )

        submode_options = [
            "🏛️ Bảng Hồ sơ Thực thể & Trọng số",
            "🔀 Công cụ Gộp Thực thể Trùng lặp (Entity Merge)",
        ]
        default_submode = submode_options[1] if get_active_curation_section(project) == "merge" else submode_options[0]
        desired_submode = str(st.session_state.get("_curation_entity_submode") or default_submode)
        if desired_submode not in submode_options:
            desired_submode = default_submode
        submode_nonce = int(st.session_state.get("_curation_entity_submode_nonce") or 0)
        sync_keyed_choice(
            "hub_entity_submode_radio",
            submode_options,
            desired_submode,
            (desired_submode, submode_nonce),
        )
        ent_subnav = st.radio(
            "Chế độ hiển thị Bước 2:",
            submode_options,
            horizontal=True,
            key="hub_entity_submode_radio",
        )
        if ent_subnav != desired_submode:
            st.session_state["_curation_entity_submode"] = ent_subnav
            st.session_state["_curation_active_section"] = "merge" if not ent_subnav.startswith("🏛️") else "entities"
            bump_sync_nonce("_curation_entity_submode_nonce")
            st.rerun()

        if ent_subnav.startswith("🏛️"):
            ent_ctx = render_entity_table(project)
            st.divider()
            render_entity_profile_inspector(project, ent_ctx.get("focused_node_id", ""))
        else:
            render_entity_merge_panel(project, show_history=False)

        # Hợp nhất toàn bộ Lịch sử Gộp thực thể + Sửa hồ sơ + Khôi phục Snapshot vào 1 expander duy nhất
        ent_merges_cnt = len(project.get("entity_merges", []))
        ent_redirects_cnt = len(project.get("node_redirects", {}))
        cur_batches_cnt = len(project.get("curation_decision_batches", []))
        st.divider()
        with st.expander(
            f"📜 Lịch sử Gộp Thực thể ({ent_merges_cnt} phiên · {ent_redirects_cnt} chuyển hướng), Sửa Hồ sơ & Khôi phục Snapshot ({cur_batches_cnt} lô)",
            expanded=False,
        ):
            hist_ent_tab, hist_batch_tab = st.tabs([
                "🔀 Lịch sử Gộp Thực thể & Chuyển hướng ID",
                "📋 Lịch sử Sửa Hồ sơ & Lô Quyết định",
            ])
            with hist_ent_tab:
                render_entity_merge_history_body(project, get_client())
            with hist_batch_tab:
                render_decision_batch_history(
                    project,
                    batch_key="curation_decision_batches",
                    title="Lịch sử Lô Thao tác Thực thể & Khôi phục Snapshot",
                    on_restore_callbacks=[
                        lambda p: reset_edc_state_if_project_changed(p, force=True),
                        lambda p: reset_curation_state_if_project_changed(p, force=True),
                    ],
                    key_prefix="hub_entity_batch",
                    use_expander=False,
                )

    elif selected_tab == "edges":
        # =========================================================================
        # BƯỚC 3: KHỬ CẠNH LẶP & KIỂM DUYỆT BẰNG CHỨNG VĂN BẢN
        # =========================================================================
        st.markdown("#### 🔬 Bước 3: Khử Cạnh Lặp theo Bộ ba & Duyệt Bằng chứng Văn bản")
        st.caption(
            "Bước hoàn thiện đồ thị cuối cùng: **(3A)** Thu gọn các cạnh lặp bộ ba `(Nguồn - Quan hệ - Đích)` phát sinh sau khi chuẩn hóa lược đồ và gộp thực thể, "
            "bảo vệ các sự kiện lịch sử độc lập; **(3B)** Xác thực trích đoạn bằng chứng nguyên văn và loại bỏ cạnh tự nối vô nghĩa."
        )

        # Bước 3A: Khử trùng Cạnh Lặp (Triple Deduplication) đặt ngay tại Phân khu Cạnh
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        hub_snap_nonce = int(st.session_state.get("_curation_snapshot_nonce") or 0)
        dup_edge_groups = compute_apparent_duplicate_edge_groups(project.get("edges", []))
        redundant_edge_count = sum(max(0, int(g.get("count", 1)) - 1) for g in dup_edge_groups)
        with st.container(border=True):
            if dup_edge_groups:
                st.info(
                    f"✨ **Bước 3A — Khử trùng Cạnh Lặp (Triple Deduplication):** "
                    f"Phát hiện **{len(dup_edge_groups)}** nhóm bộ ba trùng lặp tuyệt đối "
                    f"(tương ứng **{redundant_edge_count}** cạnh dư thừa có thể thu gọn và dồn bằng chứng)."
                )
            else:
                st.caption(
                    "✨ **Bước 3A — Khử trùng Cạnh Lặp (Triple Deduplication):** "
                    "Hiện không có nhóm bộ ba trùng lặp tuyệt đối nào. Bạn vẫn có thể mở bàn khử trùng bên dưới để quét vị từ tương đồng trên cùng cặp nút hoặc cặp đảo chiều Chủ động – Bị động."
                )
            sync_keyed_value("cb_hub_show_triple_dedup", False, (proj_id, "triple_dedup", hub_snap_nonce))
            show_triple_dedup = st.checkbox(
                "✨ Mở Bàn Gợi ý & Khử trùng Cạnh Lặp theo Bộ ba (Triple Deduplication & Bảo vệ Sự kiện Độc lập)",
                key="cb_hub_show_triple_dedup",
            )
            if show_triple_dedup:
                st.divider()
                render_triple_dedup_tab(project, get_client(), show_history=False)

        st.markdown("##### 🔬 Bước 3B — Bảng Kiểm duyệt Quan hệ, Cô lập Tự nối & Đối chiếu Bằng chứng")
        table_ctx = render_edge_curation_table_and_batch_bar(project)
        st.divider()
        render_edge_evidence_and_inspector_panel(project, table_ctx.get("focused_edge_id", ""))

        # Hợp nhất Lịch sử Kiểm duyệt Quan hệ + Lịch sử Khử trùng Bộ ba & Sự kiện Độc lập vào 1 expander duy nhất
        edge_batches_cnt = len(project.get("curation_decision_batches", []))
        dedup_hist_cnt = sum(
            1 for h in project.get("curation_history", [])
            if h.get("operation") == "collapse_duplicate_edges" or h.get("action") == "collapse_duplicate_edges"
        )
        dismissed_edges_cnt = len(project.get("not_duplicate_edge_pairs", []))
        edge_redirects_cnt = len(project.get("edge_redirects", {}))
        st.divider()
        with st.expander(
            f"📜 Lịch sử Kiểm duyệt Quan hệ ({edge_batches_cnt} lô), Khử trùng Bộ ba ({dedup_hist_cnt} phiên · {dismissed_edges_cnt} miễn trừ · {edge_redirects_cnt} chuyển hướng) & Khôi phục Snapshot",
            expanded=False,
        ):
            hist_edge_tab, hist_dedup_tab = st.tabs([
                "📋 Lịch sử Lô Kiểm duyệt Quan hệ & Khôi phục Snapshot",
                "✨ Lịch sử Khử trùng Bộ ba, Sự kiện Độc lập & Ánh xạ Cạnh",
            ])
            with hist_edge_tab:
                render_decision_batch_history(
                    project,
                    batch_key="curation_decision_batches",
                    title="Lịch sử Lô Kiểm duyệt Quan hệ & Khôi phục Snapshot",
                    on_restore_callbacks=[
                        lambda p: reset_edc_state_if_project_changed(p, force=True),
                        lambda p: reset_curation_state_if_project_changed(p, force=True),
                    ],
                    key_prefix="hub_edge_batch",
                    use_expander=False,
                )
            with hist_dedup_tab:
                render_triple_dedup_history_body(project)

    # 6. ĐIỀU HƯỚNG SANG BƯỚC TIẾP THEO
    st.divider()
    with st.container(border=True):
        col_msg, col_btn = st.columns([3.5, 1.5])
        col_msg.markdown(
            "➡️ **Hoàn tất rà soát 3 bước?** "
            "Chuyển sang Bước 5 để trực quan hóa đồ thị tri thức, kiểm tra tính toàn vẹn, xuất file JSON/ZIP hoặc đồng bộ lên Neo4j."
        )
        if col_btn.button("➡️ Chuyển sang Bước 5: Khai thác & Xuất đồ thị", type="primary", width="stretch", key="p04_btn_goto_explore"):
            navigate_to_step("explore")
            st.rerun()


