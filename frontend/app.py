"""Entrypoint Giao diện Streamlit Độc lập của KG Studio Pro."""
from __future__ import annotations

import streamlit as st

from backend.facade import get_facade
from backend.integrations.llm import LLMGateway
from frontend.components.pipeline_banner import render_pipeline_header
from frontend.pages import (
    render_catalogs_prompts_page,
    render_curation_hub_page,
    render_extraction_page,
    render_graph_export_page,
    render_projects_docs_page,
)
from frontend.state.session import (
    PAGE_LABELS,
    PIPELINE_STEPS,
    _safe_set_widget_state,
    compute_pipeline_readiness,
    ensure_session_state,
    normalize_page_label,
    on_sb_llm_key_change,
    on_sb_llm_max_in_change,
    on_sb_llm_max_out_change,
    on_sb_llm_model_change,
    on_sb_llm_provider_change,
    on_sb_llm_url_change,
    switch_llm_provider,
)
from shared.config_loader import CONFIG, save_llm_token_config_to_toml
from shared.secrets_manager import delete_api_key, get_api_key, has_persisted_key, mask_api_key, save_api_key


def main() -> None:
    st.set_page_config(
        page_title=CONFIG["app"]["page_title"],
        page_icon=CONFIG["app"]["page_icon"],
        layout="wide",
    )
    st.markdown(
        "<style>[data-testid='stSidebarNav'] { display: none !important; }</style>",
        unsafe_allow_html=True,
    )

    facade = get_facade()
    project = ensure_session_state()

    with st.sidebar:
        st.title(CONFIG["app"]["title"])
        st.caption(CONFIG["app"]["caption"])

        # 1. KHÔNG GIAN LÀM VIỆC DỰ ÁN (Project Workspace)
        existing_projects = facade.list_projects()
        cur_name = str(
            project.get("name")
            or st.session_state.get("active_project_name")
            or (existing_projects[0] if existing_projects else CONFIG["app"]["default_project_name"])
        )
        if cur_name not in existing_projects:
            existing_projects = [cur_name, *existing_projects]

        selected_proj = st.selectbox(
            "📁 Dự án đang mở",
            existing_projects,
            index=existing_projects.index(cur_name),
        )
        if selected_proj != cur_name:
            st.session_state["active_project_name"] = selected_proj
            st.rerun()

        new_proj_name = st.text_input("Tạo hoặc mở dự án theo tên", placeholder="Nhập tên dự án...")
        if st.button("➕ Mở / Tạo dự án", width="stretch") and new_proj_name.strip():
            proj = facade.load_project(new_proj_name.strip())
            facade.save_project(proj)
            st.session_state["active_project_name"] = proj.get("name", new_proj_name.strip())
            st.rerun()

        # 2. ĐIỀU HƯỚNG QUY TRÌNH 5 BƯỚC (Pipeline Navigation & Badges)
        st.divider()
        st.subheader("🧭 Quy trình 5 Bước")
        readiness = compute_pipeline_readiness(project)

        step_labels_with_badge: list[str] = []
        for s_id, p_label in zip(PIPELINE_STEPS, PAGE_LABELS):
            b = readiness.get(s_id, {}).get("badge", "○")
            step_labels_with_badge.append(f"{p_label} [{b}]")

        current_label = normalize_page_label(st.session_state.get("active_page", PAGE_LABELS[0]))
        active_idx = PAGE_LABELS.index(current_label) if current_label in PAGE_LABELS else 0

        chosen_labeled = st.radio(
            "Chọn bước trong quy trình",
            step_labels_with_badge,
            index=active_idx,
            label_visibility="collapsed",
        )
        chosen_idx = step_labels_with_badge.index(chosen_labeled)
        if chosen_idx != active_idx:
            st.session_state["active_page"] = PAGE_LABELS[chosen_idx]
            st.session_state["active_step"] = PIPELINE_STEPS[chosen_idx]
            st.rerun()

        # 3. CÀI ĐẶT KẾT NỐI LLM (Tóm tắt & Điều chỉnh nhanh trong Expander)
        st.divider()
        with st.expander("⚙️ Cài đặt LLM & Token", expanded=False):
            st.caption(f"Đang dùng: `{st.session_state['llm_provider']}` — `{st.session_state['llm_model']}`")
            st.selectbox(
                "Nhà cung cấp",
                LLMGateway.PROVIDERS,
                key="sb_llm_provider",
                on_change=on_sb_llm_provider_change,
            )

            current_prov = st.session_state["llm_provider"]
            _safe_set_widget_state(
                "sb_llm_model",
                st.session_state.setdefault("llm_model", LLMGateway.DEFAULT_MODELS.get(current_prov, "deepseek-chat")),
            )
            st.text_input("Model ID", key="sb_llm_model", on_change=on_sb_llm_model_change)

            _safe_set_widget_state(
                "sb_llm_url",
                st.session_state.setdefault("llm_base_url", LLMGateway.resolve_base_url(current_prov)),
            )
            st.text_input("Base URL", key="sb_llm_url", on_change=on_sb_llm_url_change)

            _safe_set_widget_state(
                "sb_llm_key",
                st.session_state.setdefault("llm_api_key", get_api_key(current_prov)),
            )
            st.text_input(
                "API Key (để trống nếu dùng Ollama)",
                type="password",
                key="sb_llm_key",
                on_change=on_sb_llm_key_change,
            )

            is_persisted = has_persisted_key(st.session_state["llm_provider"])
            if is_persisted:
                st.caption(f"🔒 Đã lưu an toàn: `{mask_api_key(st.session_state['llm_api_key'])}`")
            elif st.session_state["llm_api_key"]:
                st.caption("ℹ️ Khóa chỉ tạm trong phiên.")

            _safe_set_widget_state(
                "sb_llm_max_in",
                int(st.session_state.get("llm_max_input_tokens", 16000)),
            )
            st.slider(
                "📥 Max Input Tokens",
                min_value=1024,
                max_value=128000,
                step=1024,
                key="sb_llm_max_in",
                on_change=on_sb_llm_max_in_change,
            )
            _safe_set_widget_state(
                "sb_llm_max_out",
                int(st.session_state.get("llm_max_output_tokens", 16384)),
            )
            st.slider(
                "📤 Max Output Tokens",
                min_value=512,
                max_value=65536,
                step=512,
                key="sb_llm_max_out",
                on_change=on_sb_llm_max_out_change,
            )

            btn_auto_col, btn_save_col = st.columns(2)
            if btn_auto_col.button("⚡ Auto", width="stretch", key="sb_btn_auto"):
                rec = LLMGateway.recommend_token_limits(
                    st.session_state["llm_provider"],
                    st.session_state["llm_model"],
                )
                st.session_state["llm_max_input_tokens"] = rec["max_input_tokens"]
                st.session_state["llm_max_output_tokens"] = rec["max_output_tokens"]
                st.session_state["extraction_chunk_size"] = rec["recommended_chunk_size"]
                st.session_state["sb_llm_max_in"] = rec["max_input_tokens"]
                st.session_state["sb_llm_max_out"] = rec["max_output_tokens"]
                st.rerun()

            if btn_save_col.button("💾 Lưu TOML", width="stretch", key="sb_btn_save_toml"):
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
                st.success(f"Đã lưu vào `{saved_path.name}` & bảo mật API key!")

            k_save_col, k_del_col = st.columns(2)
            if k_save_col.button("🔑 Lưu Key", width="stretch", key="sb_btn_save_key", help="Lưu an toàn vào config/.secrets.toml"):
                save_api_key(st.session_state["llm_provider"], st.session_state["llm_api_key"])
                st.toast("✅ Đã lưu API key vào config/.secrets.toml!")
                st.rerun()
            if is_persisted and k_del_col.button("🗑️ Xóa Key", width="stretch", key="sb_btn_del_key", help="Xóa khỏi .secrets.toml"):
                delete_api_key(st.session_state["llm_provider"])
                st.session_state["llm_api_key"] = ""
                st.session_state["sb_llm_key"] = ""
                st.session_state["p02_llm_key"] = ""
                st.toast("🗑️ Đã xóa API key đã lưu!")
                st.rerun()

            if st.button("🔌 Kiểm tra kết nối LLM", width="stretch", key="sb_btn_test_llm"):
                ok, msg = facade.test_llm(
                    st.session_state["llm_provider"],
                    st.session_state["llm_api_key"],
                    st.session_state["llm_model"],
                    st.session_state["llm_base_url"],
                )
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    # 4. THANH TIẾN TRÌNH PIPELINE 5 BƯỚC NGANG
    render_pipeline_header(project)
    st.divider()

    # 5. ĐIỀU PHỐI HIỂN THỊ MÀN HÌNH TƯƠNG ỨNG
    active_page = normalize_page_label(st.session_state.get("active_page", PAGE_LABELS[0]))
    if active_page == PAGE_LABELS[0]:
        render_projects_docs_page(project)
    elif active_page == PAGE_LABELS[1]:
        render_catalogs_prompts_page(project)
    elif active_page == PAGE_LABELS[2]:
        render_extraction_page(project)
    elif active_page == PAGE_LABELS[3]:
        render_curation_hub_page(project)
    elif active_page == PAGE_LABELS[4]:
        render_graph_export_page(project)


if __name__ == "__main__":
    main()

