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
    compute_pipeline_readiness,
    ensure_session_state,
    navigate_to_step,
    normalize_page_label,
)
from shared.config_loader import CONFIG
from shared.secrets_manager import get_api_key, has_persisted_key


_SIDEBAR_BADGE_LABELS = {
    "✓": "✓ Xong",
    "●": "● Chờ",
    "!": "! Lưu ý",
    "○": "○ Trống",
}


def _inject_scoped_styles() -> None:
    """Áp dụng token kiểu chữ, khoảng cách và viền focus có phạm vi (tránh class DOM sinh tự động)."""
    st.markdown(
        """
        <style>
        [data-testid='stSidebarNav'] { display: none !important; }
        [data-testid='stAppViewContainer'] p,
        [data-testid='stAppViewContainer'] li {
            font-size: 1rem;
            line-height: 1.58;
        }
        [data-testid='stMainBlockContainer'] {
            padding-top: 1.5rem;
            padding-bottom: 2.5rem;
            max-width: 1400px;
        }
        button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible {
            outline: 2px solid #1D4ED8 !important;
            outline-offset: 2px !important;
        }
        @media (max-width: 900px) {
            [data-testid='stHorizontalBlock'] {
                flex-wrap: wrap !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title=CONFIG["app"]["page_title"],
        page_icon=CONFIG["app"]["page_icon"],
        layout="wide",
    )
    _inject_scoped_styles()

    facade = get_facade()
    project = ensure_session_state()

    with st.sidebar:
        st.title(CONFIG["app"]["title"])
        st.caption(CONFIG["app"]["caption"])

        # 1. KHÔNG GIAN LÀM VIỆC DỰ ÁN (Tách rõ Mở dự án có sẵn vs Tạo dự án mới)
        existing_projects = facade.list_projects()
        cur_name = str(
            project.get("name")
            or st.session_state.get("active_project_name")
            or (existing_projects[0] if existing_projects else CONFIG["app"]["default_project_name"])
        )
        if cur_name not in existing_projects:
            existing_projects = [cur_name, *existing_projects]

        selected_proj = st.selectbox(
            "📂 Mở dự án có sẵn",
            existing_projects,
            index=existing_projects.index(cur_name),
            key="sb_select_project",
        )
        if selected_proj != cur_name:
            st.session_state["active_project_name"] = selected_proj
            st.rerun()

        with st.expander("➕ Tạo dự án mới", expanded=False):
            new_proj_name = st.text_input(
                "Tên dự án mới",
                placeholder="Ví dụ: Di tích Hà Nội 2026...",
                key="sb_new_project_name",
            )
            if st.button("✨ Tạo và mở dự án mới", width="stretch", key="sb_btn_create_project"):
                cleaned = new_proj_name.strip()
                existing_lower = {p.strip().lower(): p for p in existing_projects}
                if not cleaned:
                    st.warning("⚠️ Vui lòng nhập tên dự án trước khi tạo.")
                elif cleaned.lower() in existing_lower:
                    st.info(
                        f"ℹ️ Dự án `{existing_lower[cleaned.lower()]}` đã tồn tại. "
                        "Hãy chọn ở danh sách **Mở dự án có sẵn** phía trên hoặc nhập tên khác."
                    )
                else:
                    proj = facade.load_project(cleaned)
                    facade.save_project(proj)
                    st.session_state["active_project_name"] = proj.get("name", cleaned)
                    st.rerun()

        # 2. ĐIỀU HƯỚNG CHÍNH: QUY TRÌNH 5 BƯỚC
        st.divider()
        st.subheader("🧭 Quy trình 5 Bước")
        readiness = compute_pipeline_readiness(project)

        step_labels_with_badge: list[str] = []
        for s_id, p_label in zip(PIPELINE_STEPS, PAGE_LABELS):
            b = readiness.get(s_id, {}).get("badge", "○")
            b_text = _SIDEBAR_BADGE_LABELS.get(b, b)
            step_labels_with_badge.append(f"{p_label} ({b_text})")

        current_label = normalize_page_label(st.session_state.get("active_page", PAGE_LABELS[0]))
        active_idx = PAGE_LABELS.index(current_label) if current_label in PAGE_LABELS else 0

        chosen_labeled = st.radio(
            "Chọn bước làm việc",
            step_labels_with_badge,
            index=active_idx,
            label_visibility="collapsed",
            key="sb_nav_steps_radio",
        )
        chosen_idx = step_labels_with_badge.index(chosen_labeled)
        if chosen_idx != active_idx:
            navigate_to_step(chosen_idx)
            st.rerun()

        # 3. TÓM TẮT KẾT NỐI AI (Chỉ đọc; nơi chỉnh sửa tập trung ở Bước 2)
        st.divider()
        cur_prov = str(st.session_state.get("llm_provider", LLMGateway.DEFAULT_PROVIDER))
        cur_model = str(st.session_state.get("llm_model", LLMGateway.DEFAULT_MODELS.get(cur_prov, "deepseek-chat")))
        cur_in = int(st.session_state.get("llm_max_input_tokens", 16000))
        cur_out = int(st.session_state.get("llm_max_output_tokens", 16384))
        cur_key = (st.session_state.get("llm_api_key") or get_api_key(cur_prov) or "").strip()
        is_persisted = has_persisted_key(cur_prov)

        with st.container(border=True):
            st.markdown("🤖 **Kết nối AI hiện tại**")
            st.caption(f"**{cur_prov}** · `{cur_model}`")
            if is_persisted:
                st.caption("🔒 API Key: Đã lưu an toàn")
            elif cur_key:
                st.caption("🔑 API Key: Chỉ giữ trong phiên")
            else:
                st.caption("⚠️ API Key: Chưa thiết lập")
            st.caption(f"Ngân sách: In `{cur_in:,}` · Out `{cur_out:,}`")
            if st.button("⚙️ Chỉnh kết nối ở Bước 2", width="stretch", key="sb_btn_goto_llm_setup"):
                navigate_to_step("setup")
                st.rerun()

    # 4. THANH TÓM TẮT DỰ ÁN & TRẠNG THÁI (Không cạnh tranh điều hướng với Sidebar)
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

