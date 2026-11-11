"""Màn hình 05: Khai thác Đồ thị Tri thức (G-Retriever & GraphRAG Lab) & Xuất Dữ liệu (JSON / CSV / ZIP / Neo4j).

Tuân thủ kiến trúc luồng 5 bước quy chuẩn theo layout-pipeline-proposal.md.
Tích hợp trực tiếp phòng thí nghiệm G-Retriever (PCST), HippoRAG (PPR) và Bộ Benchmark Thực nghiệm Đối sánh.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import streamlit as st

from backend.facade import compute_project_revision, get_facade
from frontend.components.export_tabs import (
    build_subgraph_dot,
    format_benchmark_csv,
    format_benchmark_markdown,
    render_benchmark_tab,
    render_g_retriever_qa_tab,
    render_training_dataset_tab,
)
from frontend.components.pipeline_banner import render_step_next_action
from frontend.state.session import navigate_to_step
from shared.config_loader import CONFIG
from shared.secrets_manager import get_api_key

# Backward compatibility aliases
_build_subgraph_dot = build_subgraph_dot
_format_benchmark_markdown = format_benchmark_markdown
_format_benchmark_csv = format_benchmark_csv
_render_g_retriever_qa_tab = render_g_retriever_qa_tab
_render_benchmark_tab = render_benchmark_tab
_render_training_dataset_tab = render_training_dataset_tab


def render_graph_export_page(project: dict) -> None:
    facade = get_facade()
    st.subheader("🕸️ 5. Khai thác Đồ thị Tri thức (G-Retriever & GraphRAG) & Xuất Dữ liệu")
    render_step_next_action("explore", project)

    nodes, edges = facade.approved_graph(project)
    problems = facade.validate_integrity(project)
    proj_id = str(project.get("project_id", "default"))

    # =========================================================================
    # PHÂN KHU 1: BÁO CÁO SỨC KHỎE ĐỒ THỊ & CHỌN NGUỒN DỮ LIỆU KHAI THÁC
    # =========================================================================
    with st.container(border=True):
        st.markdown("#### 📊 Báo cáo Sức khỏe Đồ thị Đã duyệt")
        c1, c2, c3 = st.columns(3)
        c1.metric("Thực thể (Nodes) đã duyệt", len(nodes), help="Số thực thể xuất hiện trong ít nhất một quan hệ đã duyệt")
        c2.metric("Quan hệ (Edges) đã duyệt", len(edges), help="Số quan hệ đã được kiểm duyệt và gắn nhãn 'Đã duyệt'")

        status_text = "✅ 100% Hợp lệ" if not problems else f"⚠️ {len(problems)} Cảnh báo"
        c3.metric("Tính toàn vẹn (Integrity)", status_text, help="Kiểm tra quan hệ treo, thiếu định danh hoặc vướng danh mục")

        if problems:
            st.warning("Phát hiện vấn đề toàn vẹn:\n- " + "\n- ".join(problems))
        else:
            st.caption("🔒 Tất cả các bộ ba tri thức đã được kiểm tra tính nhất quán và sẵn sàng khai thác G-Retriever / xuất bản.")

        with st.expander("📂 Tùy chọn: Nạp Đồ thị từ Gói `.zip` hoặc `.json` đã xuất để chạy G-Retriever Độc lập", expanded=False):
            st.caption(
                "Mặc định G-Retriever khai thác trực tiếp dự án đang mở. "
                "Bạn cũng có thể tải lên tệp `*_export.zip` hoặc `do_thi_da_duyet.json` để kiểm chứng khả năng hoạt động độc lập từ gói xuất."
            )
            uploaded_pkg = st.file_uploader(
                "Chọn tệp `.zip` hoặc `.json` đã xuất từ KG Studio",
                type=["zip", "json"],
                key=f"_p06_upload_pkg_{proj_id}",
            )
            ext_proj_key = f"_p06_external_graph_{proj_id}"
            if uploaded_pkg is not None:
                try:
                    loaded_ext = facade.load_project_from_export_bytes(uploaded_pkg.getvalue(), uploaded_pkg.name)
                    st.session_state[ext_proj_key] = loaded_ext
                    st.success(
                        f"✅ Đã nạp thành công gói `{uploaded_pkg.name}`: "
                        f"**{len(loaded_ext.get('nodes', []))}** thực thể, **{len(loaded_ext.get('edges', []))}** quan hệ."
                    )
                except Exception as exc:
                    st.error(f"Không thể đọc gói đồ thị: {exc}")
            if ext_proj_key in st.session_state:
                if st.button("🔄 Quay lại dùng Đồ thị của Dự án đang mở", key=f"_p06_clear_ext_{proj_id}"):
                    st.session_state.pop(ext_proj_key, None)
                    st.rerun()

    active_graph_project = st.session_state.get(f"_p06_external_graph_{proj_id}", project)

    # =========================================================================
    # PHÂN KHU 2: 4 TAB CHỨC NĂNG (G-RETRIEVER QA, BENCHMARK, TRAINING QA STUDIO, BẢN ĐỒ & XUẤT FILE)
    # =========================================================================
    tab_qa, tab_bench, tab_train_studio, tab_export = st.tabs(
        [
            "🧠 1. Hỏi đáp Đồ thị (G-Retriever PCST • HippoRAG • Naive)",
            "📊 2. Thực nghiệm Đối sánh (Benchmark Báo cáo)",
            "🧬 3. Sinh Dữ liệu Huấn luyện G-Retriever (Training QA Studio)",
            "📦 4. Bản đồ Toàn cục, Gói Sao lưu & Neo4j",
        ]
    )

    with tab_qa:
        render_g_retriever_qa_tab(facade, active_graph_project, proj_id)

    with tab_bench:
        render_benchmark_tab(facade, active_graph_project, proj_id)

    with tab_train_studio:
        render_training_dataset_tab(facade, active_graph_project, proj_id)

    with tab_export:
        if edges:
            with st.container(border=True):
                st.markdown("#### 🗺️ Bản đồ Trực quan hóa Đồ thị (Graph Visualization)")
                total_edges = len(edges)
                default_max = int(CONFIG["graph"]["max_edges"])
                default_limit = min(default_max, total_edges)
                limit_state_key = f"_p06_edge_limit_{proj_id}"
                slider_key = f"p06_graph_max_edges_{proj_id}"

                if total_edges > 1:
                    saved_limit = int(st.session_state.get(limit_state_key, default_limit))
                    clamped_limit = max(1, min(saved_limit, total_edges))

                    ctrl_c1, ctrl_c2 = st.columns([4, 1], vertical_alignment="bottom")
                    if ctrl_c2.button(
                        f"🚀 Tối đa ({total_edges})",
                        width="stretch",
                        key=f"p06_btn_max_edges_{proj_id}",
                        help="Đặt thanh trượt lên số lượng cạnh tối đa hiện có.",
                    ):
                        clamped_limit = total_edges
                        st.session_state[limit_state_key] = total_edges
                        st.session_state.pop(slider_key, None)

                    display_limit = int(
                        ctrl_c1.slider(
                            "🎚️ Kéo để tăng/giảm số lượng cạnh hiển thị",
                            min_value=1,
                            max_value=total_edges,
                            value=clamped_limit,
                            step=1,
                            key=slider_key,
                            help=f"Kéo thanh trượt để điều chỉnh từ 1 đến tối đa {total_edges} quan hệ đã duyệt.",
                        )
                    )
                    st.session_state[limit_state_key] = display_limit
                else:
                    display_limit = total_edges

                displayed_edges = edges[:display_limit]
                displayed_node_ids = {x for e in displayed_edges for x in (e["source"], e["target"])}
                st.caption(
                    f"ℹ️ Đang hiển thị **{len(displayed_edges)}/{total_edges}** quan hệ đã duyệt "
                    f"(tương ứng **{len(displayed_node_ids)}/{len(nodes)}** thực thể)."
                )

                nodes_by_id = {n["id"]: n["name"] for n in nodes}
                dot_lines = [
                    "digraph KG {",
                    '  rankdir="LR";',
                    '  node [shape=box, style="rounded,filled", fillcolor="#eef6ff", color="#3b82f6", fontname="sans-serif"];',
                    '  edge [fontname="sans-serif", color="#64748b", fontsize=10];',
                ]
                for e in displayed_edges:
                    src = nodes_by_id.get(e["source"], e["source"]).replace('"', '\\"')
                    dst = nodes_by_id.get(e["target"], e["target"]).replace('"', '\\"')
                    rel = e.get("relation", "").replace('"', '\\"')
                    dot_lines.append(f'  "{src}" -> "{dst}" [label="{rel}"];')
                dot_lines.append("}")
                st.graphviz_chart("\n".join(dot_lines))
        else:
            st.info(
                "ℹ️ Hiện chưa có quan hệ nào ở trạng thái **'Đã duyệt'** để hiển thị đồ thị. "
                "Hãy chuyển sang **Bước 4: Rà soát & Chuẩn hóa** để duyệt các quan hệ hoặc thực hiện duyệt hàng loạt."
            )

        st.divider()
        with st.container(border=True):
            st.markdown("#### 📦 Tải xuống Bộ dữ liệu Tri thức & Gói Huấn luyện G-Retriever")
            st.caption(
                "Gói ZIP bao gồm trọn bộ 11 tệp: `do_thi_da_duyet.json`, `du_an_day_du.json`, `thuc_the.csv`, `quan_he.csv`, "
                "`pyg_nodes.csv`, `pyg_edges.csv`, `train.jsonl`, `val.jsonl`, `test.jsonl`, `bo_cau_hoi_g_retriever.json` và `.jsonl`."
            )

            export_rev = compute_project_revision(project)
            info_c1, info_c2, info_c3 = st.columns(3)
            info_c1.write(f"🏷️ **Dự án**: `{project.get('name', 'N/A')}`")
            info_c2.write(f"🔢 **Revision**: `{export_rev[:10]}`")
            info_c3.write(f"📅 **Thời điểm**: `{datetime.now().strftime('%Y-%m-%d %H:%M')}`")

            export_key = f"_export_cache_{project.get('project_id', 'default')}"
            exp_cache = st.session_state.setdefault(export_key, {})

            d1, d2 = st.columns(2)
            with d1:
                if "json_bytes" not in exp_cache:
                    if st.button("🔨 Chuẩn bị tệp JSON Đã duyệt", width="stretch", key="btn_prep_json"):
                        with st.spinner("Đang chuẩn bị JSON..."):
                            exp_cache["json_bytes"] = facade.approved_json_bytes(project)
                        st.rerun()
                else:
                    st.download_button(
                        "⬇️ Tải JSON Đồ thị Đã duyệt (do_thi_da_duyet.json)",
                        data=exp_cache["json_bytes"],
                        file_name=f"{project.get('name', 'kg')}_do_thi_da_duyet.json",
                        mime="application/json",
                        width="stretch",
                        key="btn_dl_json",
                    )
                    if st.button("🔄 Làm mới tệp JSON", width="stretch", key="btn_clear_json"):
                        exp_cache.pop("json_bytes", None)
                        st.rerun()

            with d2:
                if "zip_bytes" not in exp_cache:
                    if st.button("🔨 Chuẩn bị Gói Sao lưu ZIP Đầy đủ (JSON + CSV + QA)", width="stretch", key="btn_prep_zip"):
                        with st.spinner("Đang nén gói ZIP huấn luyện..."):
                            exp_cache["zip_bytes"] = facade.export_zip(project)
                        st.rerun()
                else:
                    st.download_button(
                        "⬇️ Tải Gói Sao lưu ZIP Đầy đủ (JSON + PyG CSV + Train/Val/Test JSONL)",
                        data=exp_cache["zip_bytes"],
                        file_name=f"{project.get('name', 'kg_studio')}_export.zip",
                        mime="application/zip",
                        width="stretch",
                        key="btn_dl_zip",
                    )
                    if st.button("🔄 Làm mới gói ZIP", width="stretch", key="btn_clear_zip"):
                        exp_cache.pop("zip_bytes", None)
                        st.rerun()

        with st.expander("🗄️ Tích hợp Cơ sở dữ liệu Đồ thị Neo4j (Tùy chọn nâng cao)", expanded=False):
            st.caption("Đẩy trực tiếp các thực thể và quan hệ đã duyệt vào cơ sở dữ liệu Neo4j qua giao thức Bolt.")
            n1, n2, n3, n4 = st.columns(4)
            uri = n1.text_input("Neo4j URI", value=CONFIG["neo4j"]["uri"], key="p06_neo4j_uri")
            user = n2.text_input("Username", value=CONFIG["neo4j"]["username"], key="p06_neo4j_user")
            password = n3.text_input("Password", type="password", key="p06_neo4j_pwd")
            database = n4.text_input("Database", value=CONFIG["neo4j"]["database"], key="p06_neo4j_db")

            b1, b2 = st.columns(2)
            if b1.button("🔌 Kiểm tra kết nối Neo4j", width="stretch", key="p06_btn_test_neo4j"):
                ok, msg = facade.test_neo4j(uri, user, password, database)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
            if b2.button("🚀 Đồng bộ Đồ thị Đã duyệt lên Neo4j", type="primary", width="stretch", key="p06_btn_sync_neo4j"):
                try:
                    res = facade.sync_neo4j(project, uri, user, password, database)
                    st.success(f"Đã ghi {res['nodes_written']} thực thể và {res['edges_written']} quan hệ lên Neo4j.")
                except Exception as exc:
                    st.error(str(exc))

    # =========================================================================
    # ĐIỀU HƯỚNG QUAY LẠI HOẶC BỔ SUNG TÀI LIỆU
    # =========================================================================
    st.divider()
    with st.container(border=True):
        col_msg, col_btn_rev, col_btn_doc = st.columns([2.5, 1.25, 1.25])
        col_msg.markdown(
            "🔄 **Quy trình lặp tri thức:** "
            "Bạn có thể quay lại Bước 4 để duyệt thêm dữ kiện hoặc bổ sung thêm tài liệu ở Bước 1."
        )
        if col_btn_rev.button("🔍 Quay lại Bước 4: Rà soát", width="stretch", key="p06_btn_goto_review"):
            navigate_to_step("review")
            st.rerun()
        if col_btn_doc.button("➕ Bổ sung tài liệu ở Bước 1", width="stretch", type="primary", key="p06_btn_goto_docs"):
            navigate_to_step("documents")
            st.rerun()
