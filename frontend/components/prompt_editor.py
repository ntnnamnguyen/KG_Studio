"""Component Quản lý Phiên bản Prompt, Xem trước Request & Lịch sử theo Cấu hình.

Tuân thủ kiến trúc thiết kế trong KG_Studio/AI/features/prompt-versioning.md:
- Mỗi cấu hình sở hữu editor, draft và lịch sử độc lập, gồm baseline bộ ba tự do.
- Xem trước (Preview) request thực tế phản ánh chính xác token budget, user message và schema contract.
- Lịch sử bất biến, so sánh diff trực quan và khôi phục an toàn (tạo version mới, không sửa version cũ).
"""
from __future__ import annotations

import streamlit as st

from backend.facade import get_facade
from frontend.state.session import (
    bump_sync_nonce,
    sync_keyed_choice,
    sync_keyed_int,
    sync_keyed_value,
)
from shared.catalog_utils import edc_prompt
from shared.constants import (
    DEFAULT_EDC_PLUS_R_SETTINGS,
    EXTRACTION_MODES,
    MODE_EDC,
    MODE_EDC_PLUS_R,
    MODE_FIXED,
    MODE_FREE_TRIPLES,
)
from shared.schemas.project import EDCPlusRSettingsDTO

MODE_LABELS = {
    MODE_FIXED: "1. Danh mục cố định (Closed Catalog)",
    MODE_EDC: "2. EDC mở — Đề xuất định nghĩa (1 lượt)",
    MODE_EDC_PLUS_R: "3. EDC + R — Truy xuất quan hệ & Chuẩn hóa tự động",
    MODE_FREE_TRIPLES: "B. Bộ ba tự do — baseline (không chuẩn hóa ngữ nghĩa)",
}

ENGINE_SPECS = {
    MODE_FIXED: {
        "purpose": "Trích xuất thực thể và quan hệ bám chặt theo danh mục loại đối tượng & quan hệ đã định nghĩa sẵn.",
        "output": "Đối tượng (nodes), quan hệ (edges) và bằng chứng trích dẫn đưa vào hàng đợi kiểm duyệt Bước 4.",
        "requirements": "Cần danh mục Loại đối tượng và Quan hệ ở Mục 3; có sử dụng Từ điển Bí danh để liên kết tên gọi.",
        "limits": "Không tự đề xuất quan hệ mới ngoài danh mục cố định.",
        "uses_catalog": True,
    },
    MODE_EDC: {
        "purpose": "Cho phép AI đề xuất thêm loại đối tượng hoặc quan hệ mới kèm định nghĩa ngữ cảnh khi gặp khái niệm ngoài danh mục.",
        "output": "Đối tượng, quan hệ đưa vào Bước 4 kèm danh sách Đề xuất Lược đồ (`schema_proposals`) để người dùng duyệt/hợp nhất.",
        "requirements": "Có thể khởi đầu với danh mục nhỏ hoặc vừa; có sử dụng Từ điển Bí danh khi tạo thực thể.",
        "limits": "Cạnh có quan hệ/loại mới sẽ tạm bị chặn duyệt ở Bước 4 cho đến khi đề xuất lược đồ được xử lý.",
        "uses_catalog": True,
    },
    MODE_EDC_PLUS_R: {
        "purpose": "Truy xuất Top-K danh mục liên quan bằng Embedding (+R) trước khi trích xuất và gợi ý ghép chuẩn hóa đích (Target Alignment).",
        "output": "Đối tượng, quan hệ, đề xuất lược đồ kèm điểm gợi ý ứng viên đích và nhật ký từng bước (Step Traces).",
        "requirements": "Cần cấu hình Embedder + tham số Top-K và danh mục nền/từ điển dự án.",
        "limits": "Chạy thêm bước truy xuất vector/nhúng; gợi ý tự động chỉ dùng để hỗ trợ, không tự tính là quyết định con người nếu chưa áp dụng.",
        "uses_catalog": True,
    },
    MODE_FREE_TRIPLES: {
        "purpose": "Đường cơ sở B (Baseline B): AI trích xuất bộ ba tự do trực tiếp từ văn bản để đánh giá đối chứng độc lập.",
        "output": "Lưu bộ ba thô, chẩn đoán cấu trúc & provenance trong từng lượt chạy; KHÔNG nhập vào bảng duyệt Bước 4 hay đồ thị đã duyệt.",
        "requirements": "Chỉ cần tài liệu ở Bước 1 và kết nối AI. KHÔNG cần danh mục lược đồ hay Từ điển Bí danh.",
        "limits": "Danh mục và Từ điển ở Mục 3 không có hiệu lực trong lần chạy Baseline B. Dựng đồ thị thô trực tiếp tại Bước 5.",
        "uses_catalog": False,
    },
}


def _render_mode_selector_and_apply(facade, project: dict, proj_id: str, current_applied_mode: str) -> str:
    """Hiển thị radio chọn phương pháp trích xuất, thông số kỹ thuật và nút áp dụng."""
    st.markdown("#### 📐 2. Chọn Phương pháp Trích xuất")
    st.caption(
        f"Phương pháp đang áp dụng thực tế cho dự án: **`{MODE_LABELS.get(current_applied_mode, current_applied_mode)}`**."
    )

    prompt_nonce = int(st.session_state.get("_prompt_editor_nonce") or 0)
    sync_keyed_choice(
        "p02_radio_extraction_mode",
        EXTRACTION_MODES,
        current_applied_mode,
        (proj_id, current_applied_mode, prompt_nonce),
    )
    col_mode, col_apply = st.columns([3.5, 1.5])
    selected_mode = col_mode.radio(
        "Chọn phương pháp để xem mô tả, cấu hình & soạn thảo:",
        EXTRACTION_MODES,
        format_func=lambda k: MODE_LABELS[k],
        horizontal=True,
        key="p02_radio_extraction_mode",
    )

    spec = ENGINE_SPECS[selected_mode]
    with st.container(border=True):
        s_c1, s_c2 = st.columns(2)
        s_c1.markdown(f"- **Mục đích:** {spec['purpose']}\n- **Đầu ra:** {spec['output']}")
        s_c2.markdown(f"- **Yêu cầu:** {spec['requirements']}\n- **Giới hạn:** {spec['limits']}")

    if selected_mode == MODE_FREE_TRIPLES:
        st.info(
            "Baseline B chỉ trích xuất chủ thể, quan hệ, đối tượng và bằng chứng vào JSON. "
            "Không dùng danh mục miền, định nghĩa, schema retrieval hoặc chuẩn hóa. "
            "Kết quả được lưu riêng để đánh giá, không nhập vào đồ thị đã duyệt."
        )

    if selected_mode != current_applied_mode:
        col_apply.warning(
            f"⚠️ Bạn đang xem trước `{selected_mode}`, dự án **vẫn đang áp dụng** `{current_applied_mode}`. "
            "Chuyển bước không tự lưu phương pháp này."
        )
        if col_apply.button("🎯 Áp dụng phương pháp này cho Dự án", type="primary", width="stretch", key="btn_apply_proj_mode"):
            facade.create_snapshot(project)
            project["extraction_mode"] = selected_mode
            facade.save_project(project)
            st.success(f"Đã áp dụng phương pháp dự án sang: `{selected_mode}`!")
            st.rerun()
    else:
        col_apply.success(f"✅ Đang áp dụng: `{current_applied_mode}`")

    return selected_mode


def _render_prompt_draft_editor(
    facade,
    project: dict,
    proj_id: str,
    selected_mode: str,
    active_content: str,
    active_hash: str,
    ver_seq: int,
    ver_id: str,
    draft_key: str,
    current_draft: str,
    has_unsaved_changes: bool,
) -> tuple[str, bool]:
    """Hiển thị trình soạn thảo bản nháp prompt và nút lưu phiên bản / hủy nháp."""
    draft_nonce_key = f"_prompt_draft_nonce_{proj_id}_{selected_mode}"
    prompt_nonce = int(st.session_state.get("_prompt_editor_nonce") or 0)
    d_tag = (proj_id, selected_mode, prompt_nonce, int(st.session_state.get(draft_nonce_key) or 0))
    txt_key = f"txt_prompt_editor_{proj_id}_{selected_mode}"
    sync_keyed_value(txt_key, current_draft, d_tag)

    effective_draft = str(st.session_state.get(txt_key, current_draft))
    unsaved_now = effective_draft.strip() != active_content.strip()

    with st.container(border=True):
        hdr1, hdr2 = st.columns([3, 2])
        hdr1.markdown(f"##### ✍️ Hướng dẫn Trích xuất (Prompt cho `{selected_mode}`)")
        if unsaved_now:
            hdr2.warning(f"⚠️ Có bản nháp chưa lưu (chưa áp dụng) | Bản đang pin: **v{ver_seq}** (`{active_hash}`)")
        else:
            hdr2.success(f"🔒 Đang pin: **v{ver_seq}** (`{active_hash}`) · ID: `{ver_id}`")

        new_text = st.text_area(
            "Nội dung Hướng dẫn Trích xuất (Base Instructions)",
            height=160,
            key=txt_key,
            help=(
                "Chỉ chứa hướng dẫn trích xuất mở. Hệ thống chỉ bổ sung cấu trúc JSON bộ ba; "
                "không ghép danh mục miền, định nghĩa hoặc Top-K retrieval."
                if selected_mode == MODE_FREE_TRIPLES
                else "Chỉ chứa phần hướng dẫn cốt lõi. Hợp đồng JSON, danh mục quan hệ và Top-K retrieval sẽ được hệ thống ghép tự động khi gửi LLM."
            ),
        )
        st.session_state[draft_key] = new_text
        unsaved_now = new_text.strip() != active_content.strip()

        note_key = f"txt_note_{proj_id}_{selected_mode}"
        sync_keyed_value(note_key, "", d_tag)
        col_note, col_btn_save, col_btn_cancel = st.columns([2.5, 1.25, 1.25])
        note_val = col_note.text_input(
            "Ghi chú thay đổi",
            placeholder="Lý do sửa đổi (ví dụ: Bổ sung nguyên tắc niên đại...)",
            key=note_key,
            label_visibility="collapsed",
        )

        if col_btn_save.button(
            "💾 Lưu phiên bản mới",
            type="primary" if unsaved_now else "secondary",
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
            bump_sync_nonce(draft_nonce_key)
            bump_sync_nonce("_prompt_hist_nonce")
            if is_created:
                st.success(f"✅ Đã tạo và áp dụng phiên bản mới: **v{new_v['version']}** (`{new_v['id']}`)!")
            else:
                st.info("Nội dung không thay đổi so với phiên bản đang áp dụng.")
            st.rerun()

        if col_btn_cancel.button(
            "🔄 Hủy sửa nháp",
            disabled=not unsaved_now,
            width="stretch",
            key=f"btn_discard_draft_{proj_id}_{selected_mode}",
        ):
            st.session_state[draft_key] = active_content
            bump_sync_nonce(draft_nonce_key)
            st.rerun()

    return new_text, unsaved_now


def _render_prompt_request_preview(
    facade,
    project: dict,
    proj_id: str,
    selected_mode: str,
    new_text: str,
    ver_seq: int,
    has_unsaved_changes: bool,
) -> None:
    """Hiển thị công cụ dựng và kiểm tra Request thực tế gửi tới AI (Prompt Preview)."""
    docs = project.get("documents", [])
    st.markdown("##### 👁️ Xem trước Request thực tế gửi tới AI (Prompt Preview)")
    st.caption(
        "Xem trước payload hoàn chỉnh sau khi ghép cấu trúc JSON, giới hạn token và dựng nội dung văn bản. "
        + (
            "Baseline không sử dụng catalog hoặc retrieval."
            if selected_mode == MODE_FREE_TRIPLES
            else "Danh mục/retrieval được bổ sung theo phương pháp đang chọn."
        )
    )
    if not docs:
        st.info("Hãy tải tài liệu ở Bước 1 để xem trước prompt với văn bản thực tế.")
        return

    prev_c1, prev_c2, prev_c3 = st.columns([3, 1, 1])
    doc_names = {d["id"]: d["name"] for d in docs}
    doc_keys = list(doc_names.keys())
    sync_keyed_choice(f"prev_sel_doc_{proj_id}_{selected_mode}", doc_keys, doc_keys[0], (proj_id, selected_mode))
    selected_doc_id = prev_c1.selectbox(
        "Chọn tài liệu đối chứng",
        doc_keys,
        format_func=lambda x: doc_names.get(x, x),
        key=f"prev_sel_doc_{proj_id}_{selected_mode}",
    )
    sync_keyed_int(
        f"prev_num_chunk_{proj_id}_{selected_mode}",
        1,
        (proj_id, selected_mode),
        min_value=1,
        max_value=100,
    )
    selected_chunk_num = prev_c2.number_input(
        "Số thứ tự đoạn",
        min_value=1,
        max_value=100,
        key=f"prev_num_chunk_{proj_id}_{selected_mode}",
    )
    sync_keyed_value(
        f"prev_chk_draft_{proj_id}_{selected_mode}",
        bool(has_unsaved_changes),
        (proj_id, selected_mode, bool(has_unsaved_changes)),
    )
    use_draft = prev_c3.checkbox("Dùng bản nháp", key=f"prev_chk_draft_{proj_id}_{selected_mode}")

    preview_store_key = f"last_preview_{selected_mode}"
    preview_owner_key = f"_last_preview_proj_{selected_mode}"
    if st.session_state.get(preview_owner_key) != proj_id:
        st.session_state.pop(preview_store_key, None)
        st.session_state[preview_owner_key] = proj_id
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
            st.session_state[preview_store_key] = prepared

    prepared_req = st.session_state.get(preview_store_key)
    if not prepared_req:
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Mã băm Request", prepared_req.request_hash[:12], help=f"Full SHA256: {prepared_req.request_hash}")
    m2.metric("Ký tự Gốc / Sau Fit", f"{prepared_req.raw_chars:,} → {prepared_req.fitted_chars:,}")
    m3.metric("Max Output Clamped", f"{prepared_req.max_tokens:,} tokens")
    m4.metric("Loại Prompt", "Bản nháp ⚠️" if prepared_req.is_draft else f"Đã lưu (v{ver_seq})")

    if prepared_req.warnings:
        st.warning("Cảnh báo payload:\n" + "\n".join(f"- {w}" for w in prepared_req.warnings))

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
        st.caption(
            "Cấu trúc JSON bộ ba được bổ sung; không có schema miền hoặc retrieval:"
            if selected_mode == MODE_FREE_TRIPLES
            else "Danh mục quan hệ, hợp đồng JSON hoặc Top-K Schema được tự động ghép:"
        )
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


def _render_prompt_version_history(
    facade,
    project: dict,
    proj_id: str,
    selected_mode: str,
    active_content: str,
    ver_seq: int,
    ver_id: str,
    draft_key: str,
) -> None:
    """Hiển thị lịch sử phiên bản prompt, so sánh diff và khôi phục phiên bản."""
    st.divider()
    versions = facade.list_prompt_versions(project, selected_mode)
    st.markdown(f"##### 📜 Lịch sử Phiên bản cho `{selected_mode}` ({len(versions)} bản ghi)")
    if not versions:
        st.info("Chưa có lịch sử phiên bản nào.")
        return

    ver_labels = [
        f"v{v.get('version', 1)} · {v.get('id', '')} · {v.get('created_at', '')[:16]} "
        + (f"· Note: '{v.get('note')}' " if v.get("note") else "")
        + (" [Đang dùng]" if v.get("id") == ver_id else "")
        for v in versions
    ]
    hist_nonce = int(st.session_state.get("_prompt_hist_nonce") or 0)
    hist_sel_key = f"sb_hist_ver_{proj_id}_{selected_mode}"
    sync_keyed_choice(hist_sel_key, list(range(len(versions))), 0, (proj_id, selected_mode, len(versions), hist_nonce))
    sel_ver_idx = st.selectbox(
        "Chọn phiên bản lịch sử để kiểm tra hoặc khôi phục",
        range(len(versions)),
        format_func=lambda i: ver_labels[i],
        key=hist_sel_key,
    )
    chosen_ver = versions[sel_ver_idx]

    hist_c1, hist_c2, hist_c3 = st.columns([2, 1.5, 1.5])
    hist_c1.write(f"🏷️ ID: `{chosen_ver.get('id')}` | Nguồn: `{chosen_ver.get('origin', 'human')}`")
    hist_c1.caption(f"SHA-256: `{chosen_ver.get('content_hash')}`")

    is_currently_active = (chosen_ver.get("id") == ver_id)
    diff_flag_key = f"show_diff_{proj_id}_{selected_mode}"

    if hist_c2.button(
        "🔀 So sánh Diff với bản đang dùng",
        width="stretch",
        key=f"btn_diff_ver_{proj_id}_{selected_mode}",
    ):
        st.session_state[diff_flag_key] = not bool(st.session_state.get(diff_flag_key, False))

    if hist_c3.button(
        "↩️ Khôi phục thành Bản Mới",
        width="stretch",
        type="primary" if not is_currently_active else "secondary",
        disabled=is_currently_active,
        key=f"btn_restore_ver_{proj_id}_{selected_mode}",
    ):
        facade.create_snapshot(project)
        restored_v, _is_res = facade.restore_prompt_version(
            project,
            chosen_ver["id"],
            note=f"Khôi phục từ v{chosen_ver.get('version')} ({chosen_ver.get('id')})",
        )
        facade.save_project(project)
        st.session_state[draft_key] = restored_v["content"]
        bump_sync_nonce(f"_prompt_draft_nonce_{proj_id}_{selected_mode}")
        bump_sync_nonce("_prompt_hist_nonce")
        st.success(f"🎉 Đã khôi phục thành công! Tạo phiên bản mới: **v{restored_v['version']}**.")
        st.rerun()

    if st.session_state.get(diff_flag_key):
        diff_text = facade.diff_prompt_versions(
            active_content,
            chosen_ver.get("content", ""),
            v1_name=f"Bản đang áp dụng (v{ver_seq})",
            v2_name=f"Bản lịch sử (v{chosen_ver.get('version')})",
        )
        st.markdown("**🔍 So sánh Thay đổi (Diff):**")
        if not diff_text.strip():
            st.info("Hai phiên bản có nội dung hoàn toàn giống nhau.")
        else:
            st.code(diff_text, language="diff")

    hist_txt_key = f"txt_hist_content_{proj_id}_{selected_mode}_{chosen_ver.get('id', sel_ver_idx)}"
    sync_keyed_value(hist_txt_key, chosen_ver.get("content", ""), (proj_id, selected_mode, chosen_ver.get("id", "")))
    st.text_area(
        "Nội dung bản lịch sử đã chọn (Chỉ xem)",
        height=140,
        disabled=True,
        key=hist_txt_key,
    )


def _render_edc_plus_r_settings(facade, project: dict, proj_id: str) -> None:
    """Hiển thị biểu mẫu cấu hình tham số Schema Retriever (+R) & Target Alignment."""
    st.divider()
    cfg = EDCPlusRSettingsDTO.from_dict(project.get("edc_plus_r_settings"))
    models = facade.list_embedding_models()
    model_ids = [m["model_id"] for m in models]
    model_names = {m["model_id"]: f"{m['name']} [{m['model_id']}]" for m in models}
    if cfg.embedder_model not in model_ids:
        model_ids.append(cfg.embedder_model)
        model_names[cfg.embedder_model] = cfg.embedder_model

    prompt_nonce = int(st.session_state.get("_prompt_editor_nonce") or 0)
    cfg_tag = (proj_id, prompt_nonce)
    sync_keyed_choice(f"edcr_cfg_embedder_{proj_id}", model_ids, cfg.embedder_model, cfg_tag)
    sync_keyed_choice(f"edcr_cfg_loops_{proj_id}", [1, 2, 3], max(1, min(3, int(cfg.refinement_loops))), cfg_tag)
    sync_keyed_int(
        f"edcr_cfg_top_k_rel_{proj_id}",
        int(cfg.top_k_relations),
        cfg_tag,
        min_value=3,
        max_value=80,
    )
    sync_keyed_int(
        f"edcr_cfg_top_k_type_{proj_id}",
        int(cfg.top_k_entity_types),
        cfg_tag,
        min_value=3,
        max_value=50,
    )
    sync_keyed_value(f"edcr_cfg_auto_align_{proj_id}", float(cfg.auto_align_threshold), cfg_tag)
    sync_keyed_value(f"edcr_cfg_cand_thres_{proj_id}", float(cfg.candidate_threshold), cfg_tag)
    sync_keyed_value(f"edcr_cfg_verify_llm_{proj_id}", bool(cfg.enable_llm_verifier), cfg_tag)

    st.markdown("##### ⚙️ Cấu hình Schema Retriever (`+R`) & Target Alignment")
    c1, c2 = st.columns(2)
    chosen_model = c1.selectbox(
        "Mô hình Embedding (Model Registry)",
        model_ids,
        format_func=lambda mid: model_names.get(mid, mid),
        key=f"edcr_cfg_embedder_{proj_id}",
    )
    loops = c2.selectbox("Số vòng lặp Tinh chỉnh", [1, 2, 3], key=f"edcr_cfg_loops_{proj_id}")

    c3, c4 = st.columns(2)
    top_k_rel = c3.slider("Top-K Quan hệ (+R)", 3, 80, key=f"edcr_cfg_top_k_rel_{proj_id}")
    top_k_type = c4.slider("Top-K Loại thực thể (+R)", 3, 50, key=f"edcr_cfg_top_k_type_{proj_id}")

    c5, c6 = st.columns(2)
    auto_thres = c5.slider("Ngưỡng Tự động Chuẩn hóa", 0.50, 0.99, step=0.01, key=f"edcr_cfg_auto_align_{proj_id}")
    cand_thres = c6.slider("Ngưỡng Gợi ý Ứng viên", 0.20, 0.90, step=0.05, key=f"edcr_cfg_cand_thres_{proj_id}")

    verify_llm = st.checkbox("Bật LLM xác thực lại ứng viên Target Alignment", key=f"edcr_cfg_verify_llm_{proj_id}")

    if st.button("💾 Lưu Cấu hình Tham số EDC+R", type="primary", key=f"btn_save_edcr_params_{proj_id}"):
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


def render_prompt_management_panel(project: dict) -> None:
    """Điều phối hiển thị khu vực chọn phương pháp trích xuất và cài đặt nâng cao."""
    facade = get_facade()

    proj_id = str(project.get("project_id") or project.get("name") or "default")
    current_applied_mode = project.get("extraction_mode", MODE_FIXED)
    if current_applied_mode not in EXTRACTION_MODES:
        current_applied_mode = MODE_FIXED

    selected_mode = _render_mode_selector_and_apply(facade, project, proj_id, current_applied_mode)

    active_ver = facade.get_active_prompt_version(project, selected_mode)
    active_content = active_ver.get("content", "") if active_ver else facade.get_active_prompt_content(project, selected_mode)
    active_hash = active_ver.get("content_hash", "")[:12] if active_ver else "none"
    ver_seq = active_ver.get("version", 1) if active_ver else 1
    ver_id = active_ver.get("id", "none") if active_ver else "none"

    draft_key = f"draft_prompt_{proj_id}_{selected_mode}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = active_content

    current_draft = st.session_state[draft_key]
    has_unsaved_changes = (current_draft.strip() != active_content.strip())

    adv_label = f"🔬 Cài đặt Nâng cao & Nghiên cứu cho `{selected_mode}`"
    with st.expander(adv_label, expanded=False):
        new_text, unsaved_now = _render_prompt_draft_editor(
            facade,
            project,
            proj_id,
            selected_mode,
            active_content,
            active_hash,
            ver_seq,
            ver_id,
            draft_key,
            current_draft,
            has_unsaved_changes,
        )
        _render_prompt_request_preview(facade, project, proj_id, selected_mode, new_text, ver_seq, unsaved_now)
        _render_prompt_version_history(facade, project, proj_id, selected_mode, active_content, ver_seq, ver_id, draft_key)
        if selected_mode == MODE_EDC_PLUS_R:
            _render_edc_plus_r_settings(facade, project, proj_id)

