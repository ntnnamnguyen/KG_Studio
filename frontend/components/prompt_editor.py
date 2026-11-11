"""Component Quản lý Phiên bản Prompt, Xem trước Request & Lịch sử theo Cấu hình.

Tuân thủ kiến trúc thiết kế trong KG_Studio/AI/features/prompt-versioning.md:
- Mỗi cấu hình (closed, edc, edc_plus_r) sở hữu editor, draft và lịch sử độc lập.
- Xem trước (Preview) request thực tế phản ánh chính xác token budget, user message và schema contract.
- Lịch sử bất biến, so sánh diff trực quan và khôi phục an toàn (tạo version mới, không sửa version cũ).
"""
from __future__ import annotations

import streamlit as st

from backend.facade import get_facade
from shared.catalog_utils import edc_prompt
from shared.constants import (
    DEFAULT_EDC_PLUS_R_SETTINGS,
    EXTRACTION_MODES,
    MODE_EDC,
    MODE_EDC_PLUS_R,
    MODE_FIXED,
)
from shared.schemas.project import EDCPlusRSettingsDTO

MODE_LABELS = {
    MODE_FIXED: "1. Danh mục cố định (Closed Catalog)",
    MODE_EDC: "2. EDC mở — Đề xuất định nghĩa (1 lượt)",
    MODE_EDC_PLUS_R: "3. EDC + R — Truy xuất quan hệ & Chuẩn hóa tự động",
}


def render_prompt_management_panel(project: dict) -> None:
    facade = get_facade()

    proj_id = str(project.get("project_id") or project.get("name") or "default")
    current_applied_mode = project.get("extraction_mode", MODE_FIXED)
    if current_applied_mode not in EXTRACTION_MODES:
        current_applied_mode = MODE_FIXED

    st.markdown("#### 📐 2. Phương pháp Trích xuất & Quản lý Phiên bản Prompt")
    st.caption(
        "Mỗi chế độ trích xuất sở hữu prompt độc lập theo dự án. "
        "Mọi thay đổi đều được ghi phiên bản bất biến, hỗ trợ xem trước request thực tế và khôi phục an toàn."
    )

    # 1. BỘ CHỌN CHẾ ĐỘ TRÍCH XUẤT
    col_mode, col_apply = st.columns([3.5, 1.5])
    selected_mode = col_mode.radio(
        "Chọn chế độ trích xuất để cấu hình & soạn thảo prompt:",
        EXTRACTION_MODES,
        index=EXTRACTION_MODES.index(current_applied_mode),
        format_func=lambda k: MODE_LABELS[k],
        horizontal=True,
        key="p02_radio_extraction_mode",
    )

    if selected_mode != current_applied_mode:
        col_apply.warning(f"⚠️ Chế độ dự án đang áp dụng: **{current_applied_mode}**")
        if col_apply.button("🎯 Áp dụng chế độ này cho Dự án", type="primary", width="stretch", key="btn_apply_proj_mode"):
            facade.create_snapshot(project)
            project["extraction_mode"] = selected_mode
            facade.save_project(project)
            st.success(f"Đã chuyển chế độ dự án sang: `{selected_mode}`!")
            st.rerun()

    # 2. THÔNG TIN PHIÊN BẢN ĐANG ÁP DỤNG CHO MODE NÀY
    active_ver = facade.get_active_prompt_version(project, selected_mode)
    active_content = active_ver.get("content", "") if active_ver else facade.get_active_prompt_content(project, selected_mode)
    active_hash = active_ver.get("content_hash", "")[:12] if active_ver else "none"
    ver_seq = active_ver.get("version", 1) if active_ver else 1
    ver_id = active_ver.get("id", "none") if active_ver else "none"

    # Quản lý bản nháp (Draft) theo từng cặp project_id + configuration_id
    draft_key = f"draft_prompt_{proj_id}_{selected_mode}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = active_content

    current_draft = st.session_state[draft_key]
    has_unsaved_changes = (current_draft.strip() != active_content.strip())

    with st.container(border=True):
        hdr1, hdr2 = st.columns([3, 2])
        hdr1.markdown(f"##### ✍️ Soạn thảo Prompt cho `{selected_mode}`")
        if has_unsaved_changes:
            hdr2.warning(f"⚠️ Có thay đổi chưa lưu (Bản nháp) | Đang dùng: **v{ver_seq}** (`{active_hash}`)")
        else:
            hdr2.success(f"🔒 Đang áp dụng: **v{ver_seq}** (`{active_hash}`) · ID: `{ver_id}`")

        new_text = st.text_area(
            "Nội dung Hướng dẫn Trích xuất (Base Instructions)",
            value=current_draft,
            height=160,
            key=f"txt_prompt_editor_{proj_id}_{selected_mode}",
            help="Chỉ chứa phần hướng dẫn cốt lõi. Hợp đồng JSON, danh mục quan hệ và Top-K retrieval sẽ được hệ thống ghép tự động khi gửi LLM.",
        )
        st.session_state[draft_key] = new_text

        col_note, col_btn_save, col_btn_cancel = st.columns([2.5, 1.25, 1.25])
        note_val = col_note.text_input(
            "Ghi chú thay đổi",
            placeholder="Lý do sửa đổi (ví dụ: Bổ sung nguyên tắc niên đại...)",
            key=f"txt_note_{proj_id}_{selected_mode}",
            label_visibility="collapsed",
        )

        if col_btn_save.button(
            "💾 Lưu phiên bản mới",
            type="primary" if has_unsaved_changes else "secondary",
            disabled=not new_text.strip(),
            width="stretch",
            key=f"btn_save_ver_{proj_id}_{selected_mode}",
        ):
            facade.create_snapshot(project)
            new_v, is_created = facade.save_prompt_version(
                project,
                selected_mode,
                new_text,
                note=note_val.strip(),
                created_by="local_user",
            )
            facade.save_project(project)
            st.session_state[draft_key] = new_v["content"]
            if is_created:
                st.success(f"✅ Đã tạo và áp dụng phiên bản mới: **v{new_v['version']}** (`{new_v['id']}`)!")
            else:
                st.info("Nội dung không thay đổi so với phiên bản đang áp dụng.")
            st.rerun()

        if col_btn_cancel.button(
            "🔄 Hủy sửa nháp",
            disabled=not has_unsaved_changes,
            width="stretch",
            key=f"btn_discard_draft_{proj_id}_{selected_mode}",
        ):
            st.session_state[draft_key] = active_content
            st.rerun()

    # 3. XEM TRƯỚC REQUEST HOÀN CHỈNH (Preview Parity)
    docs = project.get("documents", [])
    with st.expander("👁️ Xem trước Request gửi tới LLM (Prompt Preview)", expanded=False):
        st.caption(
            "Xem trước nội dung thực tế sau khi ghép base instructions với catalog/retrieval, "
            "hợp đồng JSON, fit token budget và dựng user message."
        )
        if not docs:
            st.info("Hãy tải tài liệu ở Bước 1 để xem trước prompt với văn bản thực tế.")
        else:
            prev_c1, prev_c2, prev_c3 = st.columns([3, 1, 1])
            doc_names = {d["id"]: d["name"] for d in docs}
            selected_doc_id = prev_c1.selectbox(
                "Chọn tài liệu đối chứng",
                list(doc_names.keys()),
                format_func=lambda x: doc_names.get(x, x),
                key=f"prev_sel_doc_{selected_mode}",
            )
            selected_chunk_num = prev_c2.number_input("Số thứ tự đoạn", min_value=1, max_value=100, value=1, key=f"prev_num_chunk_{selected_mode}")

            use_draft = prev_c3.checkbox("Dùng bản nháp hiện tại", value=has_unsaved_changes, key=f"prev_chk_draft_{selected_mode}")

            if st.button("🔨 Dựng bản xem trước Request", width="stretch", key=f"btn_build_preview_{selected_mode}"):
                with st.spinner("Đang chuẩn bị payload theo cấu hình..."):
                    in_tokens = int(st.session_state.get("llm_max_input_tokens", 16000))
                    out_tokens = int(st.session_state.get("llm_max_output_tokens", 16384))
                    provider = st.session_state.get("llm_provider")
                    model = st.session_state.get("llm_model")
                    prepared = facade.preview_extraction_request(
                        project,
                        configuration_id=selected_mode,
                        doc_id=selected_doc_id,
                        chunk_number=int(selected_chunk_num),
                        draft_content=new_text if use_draft else None,
                        provider=provider,
                        model=model,
                        max_tokens=out_tokens,
                        max_input_tokens=in_tokens,
                    )
                    st.session_state[f"last_preview_{selected_mode}"] = prepared

            prepared_req = st.session_state.get(f"last_preview_{selected_mode}")
            if prepared_req:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Mã băm Request", prepared_req.request_hash[:12], help=f"Full SHA256: {prepared_req.request_hash}")
                m2.metric("Ký tự Gốc / Sau Fit", f"{prepared_req.raw_chars:,} → {prepared_req.fitted_chars:,}")
                m3.metric("Max Output Clamped", f"{prepared_req.max_tokens:,} tokens")
                m4.metric("Loại Prompt", "Bản nháp ⚠️" if prepared_req.is_draft else f"Đã lưu (v{ver_seq})")

                if prepared_req.warnings:
                    st.warning("Cảnh báo khi chuẩn bị payload:\n- " + "\n- ".join(prepared_req.warnings))

                p_tab1, p_tab2, p_tab3, p_tab4, p_tab5 = st.tabs([
                    "1. Base Instructions",
                    "2. Phần Ứng dụng Bổ sung",
                    "3. System Prompt Đầy đủ",
                    "4. User Message",
                    "5. Tham số & Cấu hình",
                ])
                with p_tab1:
                    st.code(prepared_req.base_instructions, language="markdown")
                with p_tab2:
                    st.caption("Danh mục quan hệ, hợp đồng JSON hoặc Top-K Schema được tự động ghép:")
                    st.code(prepared_req.appended_content or "(Không có phần bổ sung)", language="markdown")
                with p_tab3:
                    st.code(prepared_req.system_prompt, language="markdown")
                with p_tab4:
                    st.code(prepared_req.user_message, language="markdown")
                with p_tab5:
                    st.json({
                        "provider": prepared_req.provider,
                        "model": prepared_req.model,
                        "temperature": prepared_req.temperature,
                        "max_tokens": prepared_req.max_tokens,
                        "max_input_tokens": prepared_req.max_input_tokens,
                        "response_format": prepared_req.response_format,
                        "retrieval_summary": prepared_req.retrieval_summary,
                    })

    # 4. LỊCH SỬ PHIÊN BẢN, SO SÁNH DIFF & KHÔI PHỤC (Version History)
    versions = facade.list_prompt_versions(project, selected_mode)
    with st.expander(f"📜 Lịch sử Phiên bản cho `{selected_mode}` ({len(versions)} bản ghi)", expanded=False):
        if not versions:
            st.info("Chưa có lịch sử phiên bản nào.")
        else:
            ver_labels = [
                f"v{v.get('version', 1)} · {v.get('id', '')} · {v.get('created_at', '')[:16]} "
                + (f"· Note: '{v.get('note')}' " if v.get("note") else "")
                + (" [Đang dùng]" if v.get("id") == ver_id else "")
                for v in versions
            ]
            sel_ver_idx = st.selectbox(
                "Chọn phiên bản lịch sử để kiểm tra hoặc khôi phục",
                range(len(versions)),
                format_func=lambda i: ver_labels[i],
                key=f"sb_hist_ver_{selected_mode}",
            )
            chosen_ver = versions[sel_ver_idx]

            hist_c1, hist_c2, hist_c3 = st.columns([2, 1.5, 1.5])
            hist_c1.write(f"🏷️ ID: `{chosen_ver.get('id')}` | Nguồn: `{chosen_ver.get('origin', 'human')}`")
            hist_c1.caption(f"SHA-256: `{chosen_ver.get('content_hash')}`")

            is_currently_active = (chosen_ver.get("id") == ver_id)

            if hist_c2.button(
                "🔀 So sánh Diff với bản đang dùng",
                width="stretch",
                key=f"btn_diff_ver_{selected_mode}",
            ):
                st.session_state[f"show_diff_{selected_mode}"] = True

            if hist_c3.button(
                "↩️ Khôi phục thành Bản Mới",
                width="stretch",
                type="primary" if not is_currently_active else "secondary",
                disabled=is_currently_active,
                key=f"btn_restore_ver_{selected_mode}",
            ):
                facade.create_snapshot(project)
                restored_v, is_res = facade.restore_prompt_version(
                    project,
                    chosen_ver["id"],
                    note=f"Khôi phục từ v{chosen_ver.get('version')} ({chosen_ver.get('id')})",
                )
                facade.save_project(project)
                st.session_state[draft_key] = restored_v["content"]
                st.success(f"🎉 Đã khôi phục thành công! Tạo phiên bản mới: **v{restored_v['version']}**.")
                st.rerun()

            if st.session_state.get(f"show_diff_{selected_mode}"):
                diff_text = facade.diff_prompt_versions(
                    active_content,
                    chosen_ver.get("content", ""),
                    v1_name=f"Bản đang áp dụng (v{ver_seq})",
                    v2_name=f"Bản lịch sử (v{chosen_ver.get('version')})",
                )
                st.markdown("##### 🔍 So sánh Thay đổi (Diff):")
                if not diff_text.strip():
                    st.info("Hai phiên bản có nội dung hoàn toàn giống nhau.")
                else:
                    st.code(diff_text, language="diff")

            st.text_area(
                "Nội dung bản lịch sử đã chọn (Chỉ xem)",
                value=chosen_ver.get("content", ""),
                height=140,
                disabled=True,
                key=f"txt_hist_content_{selected_mode}",
            )

    # 5. CẤU HÌNH BỔ SUNG CHO CHẾ ĐỘ EDC+R
    if selected_mode == MODE_EDC_PLUS_R:
        cfg = EDCPlusRSettingsDTO.from_dict(project.get("edc_plus_r_settings"))
        models = facade.list_embedding_models()
        model_ids = [m["model_id"] for m in models]
        model_names = {m["model_id"]: f"{m['name']} [{m['model_id']}]" for m in models}
        if cfg.embedder_model not in model_ids:
            model_ids.append(cfg.embedder_model)
            model_names[cfg.embedder_model] = cfg.embedder_model

        with st.container(border=True):
            st.markdown("##### ⚙️ Cấu hình Schema Retriever (`+R`) & Target Alignment")
            c1, c2, c3 = st.columns(3)
            chosen_model = c1.selectbox(
                "Mô hình Embedding (Model Registry)",
                model_ids,
                index=model_ids.index(cfg.embedder_model),
                format_func=lambda mid: model_names.get(mid, mid),
                key="edcr_cfg_embedder",
            )
            top_k_rel = c2.slider("Top-K Quan hệ (+R)", 3, 30, int(cfg.top_k_relations), key="edcr_cfg_top_k_rel")
            top_k_type = c3.slider("Top-K Loại thực thể (+R)", 3, 25, int(cfg.top_k_entity_types), key="edcr_cfg_top_k_type")

            c4, c5, c6 = st.columns(3)
            auto_thres = c4.slider("Ngưỡng Tự động Chuẩn hóa", 0.50, 0.99, float(cfg.auto_align_threshold), 0.01, key="edcr_cfg_auto_align")
            cand_thres = c5.slider("Ngưỡng Gợi ý Ứng viên", 0.20, 0.90, float(cfg.candidate_threshold), 0.05, key="edcr_cfg_cand_thres")
            loops = c6.selectbox("Số vòng lặp Tinh chỉnh", [1, 2, 3], index=max(0, min(2, int(cfg.refinement_loops) - 1)), key="edcr_cfg_loops")
            verify_llm = st.checkbox("Bật LLM xác thực lại ứng viên Target Alignment", value=bool(cfg.enable_llm_verifier), key="edcr_cfg_verify_llm")

            if st.button("💾 Lưu Cấu hình Tham số EDC+R", type="primary", key="btn_save_edcr_params"):
                facade.create_snapshot(project)
                facade.update_edc_plus_r_settings(
                    project,
                    {
                        "embedder_model": chosen_model,
                        "top_k_relations": top_k_rel,
                        "top_k_entity_types": top_k_type,
                        "auto_align_threshold": auto_thres,
                        "candidate_threshold": cand_thres,
                        "refinement_loops": loops,
                        "enable_llm_verifier": verify_llm,
                    },
                )
                facade.save_project(project)
                st.success("Đã cập nhật tham số Schema Retriever & Target Alignment!")

