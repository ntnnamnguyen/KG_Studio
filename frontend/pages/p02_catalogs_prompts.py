"""Màn hình 02: Thiết lập Phương pháp & Danh mục Tri thức (Setup).
Theo kiến trúc chuẩn hóa đề xuất trong KG_Studio/AI/report/layout-pipeline-proposal.md.
"""
from __future__ import annotations

import streamlit as st

from backend.facade import get_facade
from backend.integrations.llm import LLMGateway
from frontend.components.gazetteer_panel import render_gazetteer_setup_tab
from frontend.components.ml_lab_panel import render_ml_lab_panel
from frontend.components.pipeline_banner import render_step_next_action
from frontend.components.prompt_editor import render_prompt_management_panel
from frontend.state.session import (
    _safe_set_widget_state,
    navigate_to_step,
    on_p02_llm_key_change,
    on_p02_llm_max_in_change,
    on_p02_llm_max_out_change,
    on_p02_llm_model_change,
    on_p02_llm_provider_change,
    on_p02_llm_url_change,
    switch_llm_provider,
)
from shared.catalog_utils import (
    apply_relations,
    catalog_bytes,
    catalog_csv_bytes,
    parse_catalog,
    relation_catalog,
)
from shared.config_loader import CONFIG, save_llm_token_config_to_toml
from shared.constants import MODE_FREE_TRIPLES
from shared.secrets_manager import delete_api_key, get_api_key, has_persisted_key, save_api_key


def render_catalogs_prompts_page(project: dict) -> None:
    facade = get_facade()

    st.subheader(f"⚙️ 2. Thiết lập Kết nối, Phương pháp & Danh mục — Dự án: {project.get('name', '')}")
    st.caption("Đây là nơi cấu hình duy nhất cho kết nối AI, phương pháp trích xuất và danh mục tri thức của dự án.")

    # 1. HÀNH ĐỘNG GỢI Ý TIẾP THEO (Next Action Callout)
    render_step_next_action("setup", project)

    # 2. VÙNG 1: KẾT NỐI MÔ HÌNH & LLM (Single Editing Source of Truth)
    current_provider = st.session_state.get("llm_provider", LLMGateway.DEFAULT_PROVIDER)
    current_model = st.session_state.setdefault("llm_model", LLMGateway.DEFAULT_MODELS.get(current_provider, "deepseek-chat"))
    has_key = bool((st.session_state.get("llm_api_key") or get_api_key(current_provider) or "").strip())
    key_badge = "🔒 Đã lưu" if has_persisted_key(current_provider) else ("🔑 Phiên tạm" if has_key else "⚠️ Chưa có Key")

    with st.expander(f"🤖 1. Kết nối Mô hình AI — {current_provider} ({current_model}) · {key_badge}", expanded=False):
        st.caption(
            "Phạm vi cấu hình: Thao tác đổi trong khung này áp dụng cho phiên làm việc hiện tại. "
            "**Lưu cấu hình mặc định** ghi vào `config/default.toml` (dùng chung mọi dự án khi mở mới); "
        )
        c_p, c_m = st.columns([1.5, 2.5])
        c_p.selectbox(
            "Nhà cung cấp LLM",
            LLMGateway.PROVIDERS,
            key="p02_llm_prov",
            on_change=on_p02_llm_provider_change,
        )

        _safe_set_widget_state("p02_llm_model", current_model)
        c_m.text_input("Tên mô hình (Model ID)", key="p02_llm_model", on_change=on_p02_llm_model_change)

        c_url, c_key = st.columns([2, 2])
        current_base_url = st.session_state.setdefault("llm_base_url", LLMGateway.resolve_base_url(current_provider))
        _safe_set_widget_state("p02_llm_url", current_base_url)
        c_url.text_input("API Base URL", key="p02_llm_url", on_change=on_p02_llm_url_change)

        current_api_key = st.session_state.setdefault("llm_api_key", get_api_key(current_provider))
        _safe_set_widget_state("p02_llm_key", current_api_key)
        c_key.text_input(
            "API Key (để trống nếu dùng Ollama cục bộ)",
            type="password",
            key="p02_llm_key",
            on_change=on_p02_llm_key_change,
        )

        is_persisted = has_persisted_key(current_provider)
        if not st.session_state.get("llm_api_key"):
            c_key.caption("⚠️ Chưa có API Key. Bắt buộc đối với DeepSeek, OpenAI, Claude, Qwen.")
        elif not is_persisted:
            c_key.caption("ℹ️ Khóa chỉ tạm thời trong phiên. Bấm **Lưu API Key an toàn** bên dưới để lưu bền vững.")

        c_tok1, c_tok2 = st.columns(2)
        _safe_set_widget_state("p02_llm_max_in", int(st.session_state.get("llm_max_input_tokens", 16000)))
        c_tok1.slider(
            "📥 Token đầu vào tối đa (Input Tokens)",
            min_value=1024,
            max_value=128000,
            step=1024,
            key="p02_llm_max_in",
            on_change=on_p02_llm_max_in_change,
            help="Ngân sách token đầu vào tối đa (bao gồm system prompt và đoạn văn bản).",
        )
        _safe_set_widget_state("p02_llm_max_out", int(st.session_state.get("llm_max_output_tokens", 16384)))
        c_tok2.slider(
            "📤 Token đầu ra tối đa (Output Tokens / max_tokens)",
            min_value=512,
            max_value=65536,
            step=512,
            key="p02_llm_max_out",
            on_change=on_p02_llm_max_out_change,
            help="Giới hạn số token tối đa cho phản hồi của mô hình.",
        )

        b1, b2, b3, b4 = st.columns([1.2, 1.2, 1.4, 1.4])
        if b1.button("🔌 Kiểm tra kết nối", width="stretch", key="p02_btn_test_conn"):
            ok, msg = facade.test_llm(
                st.session_state["llm_provider"],
                st.session_state["llm_api_key"],
                st.session_state["llm_model"],
                st.session_state["llm_base_url"],
            )
            if ok:
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")

        def _handle_reset_token_limits() -> None:
            rec = LLMGateway.recommend_token_limits(
                st.session_state["llm_provider"],
                st.session_state["llm_model"],
            )
            st.session_state["llm_max_input_tokens"] = rec["max_input_tokens"]
            st.session_state["llm_max_output_tokens"] = rec["max_output_tokens"]
            st.session_state["extraction_chunk_size"] = rec["recommended_chunk_size"]
            _safe_set_widget_state("p02_llm_max_in", rec["max_input_tokens"])
            _safe_set_widget_state("sb_llm_max_in", rec["max_input_tokens"])
            _safe_set_widget_state("p02_llm_max_out", rec["max_output_tokens"])
            _safe_set_widget_state("sb_llm_max_out", rec["max_output_tokens"])

        b2.button("⚡ Đặt lại theo Model", width="stretch", key="p02_btn_auto_tok", on_click=_handle_reset_token_limits)

        if b3.button("💾 Lưu cấu hình mặc định", width="stretch", key="p02_btn_save_def_toml", help="Lưu model và giới hạn token vào config/default.toml"):
            saved_path = save_llm_token_config_to_toml(
                provider_key=LLMGateway.provider_key(st.session_state["llm_provider"]),
                model=st.session_state["llm_model"],
                base_url=st.session_state["llm_base_url"],
                max_input_tokens=int(st.session_state["llm_max_input_tokens"]),
                max_output_tokens=int(st.session_state["llm_max_output_tokens"]),
                chunk_size=int(st.session_state.get("extraction_chunk_size", CONFIG["extraction"]["chunk_size"])),
            )
            if st.session_state["llm_api_key"]:
                save_api_key(st.session_state["llm_provider"], st.session_state["llm_api_key"])
            st.success(f"Đã lưu vào `{saved_path.name}` thành công!")

        def _handle_delete_api_key() -> None:
            delete_api_key(st.session_state["llm_provider"])
            st.session_state["llm_api_key"] = ""
            _safe_set_widget_state("sb_llm_key", "")
            _safe_set_widget_state("p02_llm_key", "")

        if is_persisted:
            b4.button("🗑️ Xóa API Key đã lưu", width="stretch", key="p02_btn_del_key", on_click=_handle_delete_api_key, help="Xóa API Key khỏi config/.secrets.toml")
        else:
            if b4.button("🔑 Lưu API Key an toàn", width="stretch", key="p02_btn_save_key", help="Lưu bảo mật vào config/.secrets.toml (bỏ qua bởi Git)"):
                save_api_key(st.session_state["llm_provider"], st.session_state["llm_api_key"])
                st.toast("✅ Đã lưu API key an toàn vào config/.secrets.toml!")
                st.rerun()

    # 3. VÙNG 2: PHƯƠNG PHÁP TRÍCH XUẤT & SOẠN THẢO PROMPT
    st.divider()
    render_prompt_management_panel(project)

    # 4. VÙNG 3: DANH MỤC TRI THỨC & TỪ ĐIỂN MIỀN CỦA DỰ ÁN (Full-width Catalog & Gazetteer Tabs)
    st.divider()
    st.markdown("#### 📚 3. Danh mục Lược đồ & Từ điển Tri thức của Dự án")
    applied_mode = str(project.get("extraction_mode") or "closed")
    if applied_mode == MODE_FREE_TRIPLES:
        st.warning(
            "⚠️ **Lưu ý phạm vi tác dụng:** Dự án đang áp dụng chế độ **Baseline B (Bộ ba tự do)**. "
            "Engine Baseline B **KHÔNG sử dụng** danh mục loại đối tượng, quan hệ hay từ điển bí danh bên dưới khi trích xuất. "
            "Dữ liệu bạn lưu ở đây vẫn được giữ nguyên nếu sau này chuyển sang `closed`, `edc` hoặc `edc_plus_r`."
        )
    else:
        st.caption(
            f"Danh mục này **đang có hiệu lực** với phương pháp `{applied_mode}`: định hình các loại đối tượng, quan hệ chuẩn và ánh xạ bí danh cho dự án hiện tại."
        )

    rel_rows = relation_catalog(project)
    type_rows = project.get("entity_types", [])
    gaz_rows = facade.list_gazetteer_entries(project)

    cat_tab1, cat_tab2, cat_tab3 = st.tabs([
        f"🏷️ Loại thực thể / Đối tượng ({len(type_rows)} loại)",
        f"🔗 Loại quan hệ ({len(rel_rows)} quan hệ)",
        f"📚 Từ điển Bí danh & Địa danh ({len(gaz_rows)} mục)",
    ])

    with cat_tab1:
        st.caption("Danh sách các phân loại đối tượng hợp lệ trong đồ thị (ví dụ: di tích, nhân vật, địa danh, niên đại...).")
        up_type = st.file_uploader(
            "📥 Tải lên file JSON hoặc CSV Loại thực thể (cột: name, description, definition)",
            type=["json", "csv"],
            key="p02_up_type",
        )
        if up_type is not None:
            t_c1, t_c2 = st.columns(2)
            if t_c1.button("⚡ Nạp đè toàn bộ", key="btn_apply_type_replace", width="stretch"):
                try:
                    parsed = parse_catalog(up_type.getvalue(), "entity_types", filename=up_type.name)
                    facade.create_snapshot(project)
                    project["entity_types"] = parsed
                    facade.save_project(project)
                    st.success(f"Đã nạp {len(parsed)} loại thực thể từ `{up_type.name}`!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi đọc file: {exc}")
            if t_c2.button("➕ Gộp thêm vào mục cũ", key="btn_apply_type_merge", width="stretch"):
                try:
                    parsed = parse_catalog(up_type.getvalue(), "entity_types", filename=up_type.name)
                    existing = {t["name"].strip().lower() for t in type_rows if t.get("name")}
                    added = [p for p in parsed if p["name"].strip().lower() not in existing]
                    facade.create_snapshot(project)
                    project["entity_types"] = type_rows + added
                    facade.save_project(project)
                    st.success(f"Đã gộp thêm {len(added)} loại thực thể mới từ `{up_type.name}`!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi gộp file: {exc}")

        edited_types = st.data_editor(
            type_rows,
            num_rows="dynamic",
            width="stretch",
            key="ed_types",
            column_config={
                "name": st.column_config.TextColumn("Tên loại thực thể (name)", required=True),
                "description": st.column_config.TextColumn("Mô tả ngắn (description)"),
                "definition": st.column_config.TextColumn("Định nghĩa phạm vi chi tiết (definition)"),
            },
        )
        if type_rows:
            d_c1, d_c2 = st.columns(2)
            d_c1.download_button(
                "📤 Tải entity_types.json",
                data=catalog_bytes(type_rows, "entity_types"),
                file_name=f"{project.get('name', 'project')}_entity_types.json",
                mime="application/json",
                key="btn_dl_types",
                width="stretch",
            )
            d_c2.download_button(
                "📤 Tải entity_types.csv (Excel)",
                data=catalog_csv_bytes(type_rows, "entity_types"),
                file_name=f"{project.get('name', 'project')}_entity_types.csv",
                mime="text/csv",
                key="btn_dl_types_csv",
                width="stretch",
            )

    with cat_tab2:
        st.caption("Danh sách các nhãn quan hệ kết nối giữa các thực thể (ví dụ: tọa lạc tại, thờ phụng, xây dựng vào...).")
        up_rel = st.file_uploader(
            "📥 Tải lên file JSON hoặc CSV Quan hệ (cột: name, description, definition)",
            type=["json", "csv"],
            key="p02_up_rel",
        )
        if up_rel is not None:
            r_c1, r_c2 = st.columns(2)
            if r_c1.button("⚡ Nạp đè toàn bộ", key="btn_apply_rel_replace", width="stretch"):
                try:
                    parsed = parse_catalog(up_rel.getvalue(), "relations", filename=up_rel.name)
                    facade.create_snapshot(project)
                    apply_relations(project, parsed)
                    facade.save_project(project)
                    st.success(f"Đã nạp {len(parsed)} quan hệ từ `{up_rel.name}`!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi đọc file: {exc}")
            if r_c2.button("➕ Gộp thêm vào mục cũ", key="btn_apply_rel_merge", width="stretch"):
                try:
                    parsed = parse_catalog(up_rel.getvalue(), "relations", filename=up_rel.name)
                    existing = {r["name"].strip().lower() for r in rel_rows if r.get("name")}
                    added = [p for p in parsed if p["name"].strip().lower() not in existing]
                    facade.create_snapshot(project)
                    apply_relations(project, rel_rows + added)
                    facade.save_project(project)
                    st.success(f"Đã gộp thêm {len(added)} quan hệ mới từ `{up_rel.name}`!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi gộp file: {exc}")

        edited_rels = st.data_editor(
            rel_rows,
            num_rows="dynamic",
            width="stretch",
            key="ed_rels",
            column_config={
                "name": st.column_config.TextColumn("Tên quan hệ (name)", required=True),
                "description": st.column_config.TextColumn("Mô tả ngắn (description)"),
                "definition": st.column_config.TextColumn("Định nghĩa phạm vi chi tiết (definition)"),
            },
        )
        if rel_rows:
            dr_c1, dr_c2 = st.columns(2)
            dr_c1.download_button(
                "📤 Tải relations.json",
                data=catalog_bytes(rel_rows, "relations"),
                file_name=f"{project.get('name', 'project')}_relations.json",
                mime="application/json",
                key="btn_dl_rels",
                width="stretch",
            )
            dr_c2.download_button(
                "📤 Tải relations.csv (Excel)",
                data=catalog_csv_bytes(rel_rows, "relations"),
                file_name=f"{project.get('name', 'project')}_relations.csv",
                mime="text/csv",
                key="btn_dl_rels_csv",
                width="stretch",
            )

    with cat_tab3:
        edited_gaz = render_gazetteer_setup_tab(project)

    # Nút Lưu Danh mục
    save_c1, save_c2 = st.columns([2, 1])
    with save_c1:
        if st.button("💾 Lưu Toàn bộ Thay đổi Danh mục", type="primary", key="btn_save_catalogs", width="stretch"):
            facade.create_snapshot(project)
            clean_rels = [r for r in edited_rels if isinstance(r, dict) and (r.get("name") or "").strip()]
            clean_types = [t for t in edited_types if isinstance(t, dict) and (t.get("name") or "").strip()]
            prompt_text = project.get("prompt", "")
            facade.save_prompt_settings(project, prompt_text, clean_rels, clean_types)
            facade.save_project(project)

            cur_gaz_sig = [(r["alias"], r["canonical_name"], r["kind"]) for r in gaz_rows]
            new_gaz_sig = sorted(
                [(r["alias"], r["canonical_name"], r["kind"]) for r in edited_gaz],
                key=lambda x: (x[1].lower(), x[0].lower()),
            )
            if sorted(cur_gaz_sig, key=lambda x: (x[1].lower(), x[0].lower())) != new_gaz_sig:
                facade.replace_gazetteer_entries(
                    project,
                    edited_gaz,
                    source="manual_editor",
                    expected_revision=facade.project_revision(project),
                )

            st.success("✅ Đã lưu danh mục lược đồ và từ điển của dự án thành công!")
            st.rerun()
    with save_c2:
        if (rel_rows or type_rows) and st.button("🗑️ Xóa sạch danh mục", key="btn_clear_catalogs", width="stretch"):
            facade.create_snapshot(project)
            facade.save_prompt_settings(project, project.get("prompt", ""), [], [])
            facade.save_project(project)
            st.warning("Đã làm trống toàn bộ danh mục của dự án!")
            st.rerun()

    # 5. VÙNG 4: PHÒNG THÍ NGHIỆM ACTIVE LEARNING & ML LAB (Single-level Research Expander)
    st.divider()
    with st.expander("🧪 Khu Nghiên cứu: Active Learning & ML Lab (Độc lập với luồng cơ bản)", expanded=False):
        render_ml_lab_panel(project, facade.save_project, use_expander=False)

    # 6. NÚT CHUYỂN BƯỚC TIẾP THEO
    st.divider()
    c_back, c_next = st.columns([1, 2])
    if c_next.button("➡️ Chuyển sang Bước 3: Trích xuất tri thức", type="primary", width="stretch", key="p02_btn_next_step"):
        navigate_to_step("extraction")
        st.rerun()
