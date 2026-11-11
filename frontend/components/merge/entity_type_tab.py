"""Tab 4: Chuẩn hóa & Gộp Loại Thực thể (Entity Type Deduplication & Semantic Clustering)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import streamlit as st

from backend.integrations.llm.providers import DEFAULT_MODELS, PROVIDERS
from frontend.client import FrontendClient
from frontend.state.session import (
    reset_curation_state_if_project_changed,
    reset_edc_state_if_project_changed,
)


def render_entity_type_merge_tab(
    project: dict,
    client: FrontendClient,
    m_state: dict[str, Any],
) -> None:
    """Nội dung Tab: Chuẩn hóa & Gộp Loại Thực thể (Entity Type Deduplication & Semantic Clustering)."""
    # 1. QUÉT & GOM CỤM LOẠI THỰC THỂ BẰNG AI
    with st.container(border=True):
        st.markdown("#### 🤖 1. Quét & Gom cụm Loại Thực thể bằng AI (DeepSeek Semantic Clustering)")
        st.caption(
            "Sử dụng LLM (DeepSeek) để tự động phát hiện các loại thực thể mang ý nghĩa tương đương hoặc biến thể diễn đạt "
            "(ví dụ: 'di tích lịch sử', 'công trình kiến trúc', 'di tích văn hóa' -> gom về 'di tích'; hoặc 'danh nhân', 'vua chúa' -> 'nhân vật lịch sử'). "
            "Hệ thống sẽ chuẩn hóa trường `kind` của toàn bộ node trên đồ thị và lưu các biến thể vào `aliases` của lược đồ loại thực thể."
        )

        c_prov, c_mod, c_key = st.columns([1.5, 1.5, 3.0])
        default_prov = st.session_state.get("llm_provider", "DeepSeek")
        if default_prov not in PROVIDERS:
            default_prov = "DeepSeek" if "DeepSeek" in PROVIDERS else PROVIDERS[0]
        sel_prov = c_prov.selectbox(
            "Nhà cung cấp LLM",
            PROVIDERS,
            index=PROVIDERS.index(default_prov),
            key=f"ai_type_prov_{project.get('project_id', 'curr')}",
        )
        def_model = DEFAULT_MODELS.get(sel_prov, "deepseek-chat")
        curr_model = st.session_state.get("llm_model") or def_model
        sel_model = c_mod.text_input(
            "Mô hình",
            value=curr_model,
            key=f"ai_type_mod_{project.get('project_id', 'curr')}",
        )
        curr_key = st.session_state.get("llm_api_key", "")
        sel_key = c_key.text_input(
            "API Key",
            value=curr_key,
            type="password",
            key=f"ai_type_key_{project.get('project_id', 'curr')}",
            help="API Key của DeepSeek hoặc nhà cung cấp đã chọn.",
        )

        scope_tcol1, _ = st.columns([3.0, 3.0])
        type_scope_choices = {
            "top_50": "Top 50 loại thực thể phổ biến nhất (Khuyến nghị)",
            "top_100": "Top 100 loại thực thể phổ biến nhất",
            "freq_ge_2": "Loại thực thể có từ 2 node trở lên (freq >= 2)",
            "all": "Toàn bộ loại thực thể hiện có trên đồ thị (Tất cả)",
        }
        sel_type_scope_key = f"ai_type_scope_{project.get('project_id', 'curr')}"
        curr_type_scope = st.session_state.get(sel_type_scope_key, "top_50")
        if curr_type_scope not in type_scope_choices:
            curr_type_scope = "top_50"
        chosen_type_scope = scope_tcol1.selectbox(
            "Phạm vi loại thực thể gửi tới AI (Scan Scope)",
            options=list(type_scope_choices.keys()),
            index=list(type_scope_choices.keys()).index(curr_type_scope),
            format_func=lambda k: type_scope_choices[k],
            key=f"sb_{sel_type_scope_key}",
            help="Giới hạn phạm vi giúp context prompt ngắn gọn và xử lý nhanh chóng.",
        )
        st.session_state[sel_type_scope_key] = chosen_type_scope

        # --- KHU VỰC ĐIỀU CHỈNH PROMPT & CHỈ DẪN GOM NHÓM LOẠI THỰC THỂ ---
        with st.expander("📝 Tùy chỉnh Prompt & Chỉ dẫn Gom cụm Loại Thực thể (Custom Instructions)", expanded=False):
            st.caption(
                "Bạn có thể bổ sung các quy tắc phân loại cụ thể (ví dụ: gom các loại công trình tín ngưỡng về 'di tích tôn giáo', "
                "giữ tách biệt giữa 'di tích' và 'địa danh hành chính', hoặc ưu tiên tên danh mục chuẩn)."
            )
            type_custom_inst = st.text_area(
                "Chỉ dẫn / Quy tắc gom loại thực thể bổ sung cho AI (Prompt Instructions)",
                value=st.session_state.get(f"ai_type_custom_inst_{project.get('project_id', 'curr')}", ""),
                placeholder="Ví dụ: Gom các loại thực thể chùa, đền, miếu về loại chuẩn 'di tích tôn giáo'; Tách biệt 'vua chúa' thành 'nhân vật lịch sử'...",
                key=f"ta_ai_type_custom_inst_{project.get('project_id', 'curr')}",
                help="Các chỉ dẫn này sẽ được tiêm trực tiếp vào prompt gửi cho DeepSeek/LLM với độ ưu tiên cao nhất.",
            )
            st.session_state[f"ai_type_custom_inst_{project.get('project_id', 'curr')}"] = type_custom_inst

            col_pt_btn, _ = st.columns([2.5, 3.5])
            show_type_prompt_preview = col_pt_btn.checkbox(
                "👁️ Xem trước toàn bộ Prompt gửi LLM",
                value=bool(st.session_state.get(f"ai_type_show_prompt_{project.get('project_id', 'curr')}", False)),
                key=f"cb_ai_type_show_prompt_{project.get('project_id', 'curr')}",
            )
            st.session_state[f"ai_type_show_prompt_{project.get('project_id', 'curr')}"] = show_type_prompt_preview

            if show_type_prompt_preview:
                preview_pt = client.preview_clustering_prompt(
                    project, kind="entity_types", custom_instructions=type_custom_inst, scope=chosen_type_scope
                )
                st.caption(f"Độ dài Prompt: **{len(preview_pt):,}** ký tự (~{len(preview_pt)//3.5:.0f} tokens)")
                st.markdown("**Bản xem trước Prompt hoàn chỉnh:**")
                st.code(preview_pt, language="markdown")

        btn_scan_col, _ = st.columns([2.2, 3.8])
        if btn_scan_col.button(
            "🤖 Bắt đầu Quét & Gom cụm Loại Thực thể bằng AI",
            key=f"btn_scan_type_ai_{project.get('project_id', 'curr')}",
            type="primary",
        ):
            with st.spinner("Đang gửi yêu cầu tới DeepSeek API để phân tích ngữ nghĩa và gom cụm loại thực thể..."):
                try:
                    custom_ti = st.session_state.get(f"ai_type_custom_inst_{project.get('project_id', 'curr')}", "")
                    scan_res = client.scan_semantic_clusters(
                        project,
                        kind="entity_types",
                        scope=chosen_type_scope,
                        provider=sel_prov,
                        api_key=sel_key,
                        model=sel_model,
                        custom_instructions=custom_ti,
                    )
                    st.session_state[f"ai_type_clusters_{project.get('project_id', 'curr')}"] = scan_res
                    if scan_res.get("clusters_count", 0) > 0:
                        st.success(f"Đã phát hiện {scan_res['clusters_count']} cụm loại thực thể tương đương từ {scan_res['scanned_items_count']} loại!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi khi quét gom cụm: {exc}")

        ai_res = st.session_state.get(f"ai_type_clusters_{project.get('project_id', 'curr')}")
        if ai_res:
            if ai_res.get("clusters"):
                st.markdown("---")
                st.markdown(f"##### 🎯 Đề xuất Gom cụm Loại Thực thể ({len(ai_res['clusters'])} cụm được tìm thấy từ {ai_res.get('scanned_items_count', 0)} loại)")

                if ai_res.get("used_prompt"):
                    with st.expander("📄 Xem lại Prompt đã gửi cho lượt quét này", expanded=False):
                        st.code(ai_res["used_prompt"], language="markdown")

                selected_type_clusters = []
                for c in ai_res["clusters"]:
                    cid = c["id"]
                    c_box = st.container(border=True)
                    col_chk, col_info = c_box.columns([0.8, 5.2])
                    is_checked = col_chk.checkbox("Chọn", value=True, key=f"chk_ai_type_{cid}")
                    with col_info:
                        st.markdown(f"**Tên chuẩn hóa:** `{c['canonical_name']}` &nbsp;|&nbsp; **Số thực thể ảnh hưởng:** `{c['affected_count']}` thực thể")
                        syns_str = ", ".join(f"`{s}`" for s in c["synonyms"])
                        st.markdown(f"**Các biến thể sẽ gộp về tên chuẩn:** {syns_str}")
                        st.caption(f"💡 *Lý do ngữ nghĩa:* {c['reason']}")
                    if is_checked:
                        selected_type_clusters.append(c)

                if st.button(
                    f"🚀 Áp dụng Gom cụm cho {len(selected_type_clusters)} cụm loại thực thể đã chọn",
                    disabled=len(selected_type_clusters) == 0,
                    type="primary",
                    key=f"btn_apply_ai_type_{project.get('project_id', 'curr')}",
                ):
                    try:
                        res_apply = client.apply_semantic_clusters(
                            project,
                            kind="entity_types",
                            approved_clusters=selected_type_clusters,
                            note="Gom cụm loại thực thể tự động bằng DeepSeek AI",
                        )
                        st.session_state.pop(f"ai_type_clusters_{project.get('project_id', 'curr')}", None)
                        reset_edc_state_if_project_changed(project)
                        reset_curation_state_if_project_changed(project)
                        st.success(f"Đã gộp thành công {res_apply.applied_count} loại thực thể trên đồ thị!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Lỗi khi áp dụng gộp: {exc}")
            else:
                st.markdown("---")
                st.warning(
                    f"ℹ️ Đã quét xong **{ai_res.get('scanned_items_count', 0)}** loại thực thể trong phạm vi đã chọn, "
                    "nhưng AI không phát hiện nhóm từ đồng nghĩa nào cần gom cụm, hoặc các đề xuất trả về không khớp với danh sách loại thực thể."
                )
                if ai_res.get("raw_response"):
                    with st.expander("🔍 Xem phản hồi gốc từ DeepSeek API (Raw Response)", expanded=False):
                        st.code(ai_res["raw_response"], language="json")
                if ai_res.get("used_prompt"):
                    with st.expander("📄 Xem lại Prompt đã gửi", expanded=False):
                        st.code(ai_res["used_prompt"], language="markdown")

    # 2. BÀN GỘP LOẠI THỰC THỂ THỦ CÔNG
    with st.container(border=True):
        st.markdown("#### 📌 2. Bàn Chuẩn hóa & Gộp Loại Thực thể Thủ công")
        st.caption("Cho phép tự chọn một hoặc nhiều loại thực thể nguồn để gộp về một loại đích.")
        nodes = project.get("nodes", [])
        kind_counts = Counter(str(n.get("kind", "")).strip() for n in nodes if n.get("kind"))
        cat_types = {
            (t.get("name") if isinstance(t, dict) else str(t)).strip()
            for t in project.get("entity_types", [])
            if (t.get("name") if isinstance(t, dict) else str(t)).strip()
        }
        all_unique_kinds = sorted(set(kind_counts.keys()) | cat_types)
        if all_unique_kinds:
            c_src, c_tgt = st.columns([1.5, 1.5])
            src_kinds = c_src.multiselect(
                "Chọn các loại nguồn cần gộp (bị thay thế)",
                all_unique_kinds,
                format_func=lambda k: f"{k} ({kind_counts.get(k, 0)} thực thể)",
                key=f"ms_manual_src_type_{project.get('project_id', 'curr')}",
            )
            tgt_kind = c_tgt.selectbox(
                "Chọn loại đích chuẩn (giữ lại)",
                all_unique_kinds,
                format_func=lambda k: f"{k} ({kind_counts.get(k, 0)} thực thể)",
                key=f"sb_manual_tgt_type_{project.get('project_id', 'curr')}",
            )
            valid_srcs = [s for s in src_kinds if s != tgt_kind]
            if st.button(
                f"⚡ Gộp {len(valid_srcs)} loại nguồn về '{tgt_kind}'",
                disabled=len(valid_srcs) == 0,
                key=f"btn_manual_type_merge_{project.get('project_id', 'curr')}",
            ):
                try:
                    res = client.apply_semantic_clusters(
                        project,
                        kind="entity_types",
                        approved_clusters=[{"canonical_name": tgt_kind, "synonyms": valid_srcs}],
                        note=f"Gộp loại thực thể thủ công: {', '.join(valid_srcs)} -> {tgt_kind}",
                    )
                    reset_edc_state_if_project_changed(project)
                    reset_curation_state_if_project_changed(project)
                    st.success(f"Đã gộp thành công {res.applied_count} loại thực thể về '{tgt_kind}'!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi: {exc}")
        else:
            st.info("Chưa có loại thực thể nào trong dự án.")

    # 3. LỊCH SỬ GỘP LOẠI THỰC THỂ
    with st.container(border=True):
        st.markdown("#### 📜 3. Lịch sử Các Phiên Gộp Loại Thực thể")
        merges = project.get("entity_type_merges", [])
        if merges:
            st.dataframe(
                [
                    {
                        "Mã phiên": m.get("merge_id", ""),
                        "Thời điểm": m.get("at", ""),
                        "Người thực hiện": m.get("actor", ""),
                        "Số loại đã gộp": m.get("merged_types_count", len(m.get("mappings", {}))),
                        "Số node bị ảnh hưởng": m.get("affected_node_count", 0),
                        "Ghi chú": m.get("note", ""),
                    }
                    for m in reversed(merges)
                ],
                width="stretch",
                hide_index=True,
            )
            latest_snap = str(merges[-1].get("snapshot_path") or "")
            if latest_snap and Path(latest_snap).exists():
                confirm_undo = st.checkbox(
                    f"Tôi xác nhận khôi phục toàn dự án về snapshot trước phiên gộp `{merges[-1].get('merge_id', '')}`",
                    key="chk_restore_type_merge_snap",
                )
                if st.button(
                    "⏪ Khôi phục toàn dự án về Snapshot trước phiên gộp loại thực thể này",
                    disabled=not confirm_undo,
                    key="btn_restore_type_merge_snap",
                ):
                    client.restore_snapshot(project, latest_snap)
                    reset_edc_state_if_project_changed(project)
                    reset_curation_state_if_project_changed(project)
                    st.success("Đã khôi phục dự án về snapshot trước khi gộp loại thực thể.")
                    st.rerun()
        else:
            st.info("Chưa có phiên gộp loại thực thể nào được ghi nhận.")
