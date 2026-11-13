"""Màn hình 05: Khai thác Đồ thị Tri thức (G-Retriever & GraphRAG Lab) & Xuất Dữ liệu (JSON / CSV / ZIP / Neo4j).

Tuân thủ kiến trúc luồng 5 bước quy chuẩn theo layout-pipeline-proposal.md.
Tích hợp trực tiếp phòng thí nghiệm G-Retriever (PCST), HippoRAG (PPR) và Bộ Benchmark Thực nghiệm Đối sánh.
"""
from __future__ import annotations

from datetime import datetime
import json
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
from frontend.components.graph_source import select_graph_snapshot
from frontend.components.graph_view import build_graph_dot
from frontend.composition import get_ui_composition
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

    graph_service = get_ui_composition().graph_qa_service
    selected = select_graph_snapshot(project, graph_service)
    if selected is None:
        return
    snapshot, source_selection = selected
    current_approved = source_selection == "approved"
    nodes, edges = snapshot.nodes, snapshot.edges
    problems = graph_service.validate_integrity(project) if current_approved else [
        f"{item.get('code')} · run {item.get('run_id', '')} · triple {item.get('triple_index', '')}"
        for item in snapshot.diagnostics
    ]
    proj_id = str(project.get("project_id", "default"))

    # =========================================================================
    # PHÂN KHU 1: BÁO CÁO SỨC KHỎE ĐỒ THỊ & CHỌN NGUỒN DỮ LIỆU KHAI THÁC
    # =========================================================================
    source_badges = {
        "approved": ("🟢 ĐỒ THỊ ĐÃ ĐƯỢC NGƯỜI DÙNG KIỂM DUYỆT (Approved KG)", "success"),
        "baseline": ("🟡 ĐỒ THỊ THÔ TỪ AI — CHƯA QUA KIỂM DUYỆT (Baseline B)", "warning"),
        "external": ("🔵 ĐỒ THỊ NẠP TỪ TỆP NGOÀI (External Snapshot)", "info"),
    }
    badge_text, badge_level = source_badges.get(
        source_selection, (f"📊 Nguồn: {source_selection}", "info")
    )

    with st.container(border=True):
        st.markdown(f"#### 📊 Đồ thị đang chọn: {source_selection} / {snapshot.source}")
        getattr(st, badge_level)(badge_text)
        c1, c2, c3 = st.columns(3)
        c1.metric("Nodes", len(nodes))
        c2.metric("Edges / observations", len(edges))

        status_text = "Không có lỗi cấu trúc được báo" if not problems else f"⚠️ {len(problems)} Cảnh báo"
        c3.metric("Tính toàn vẹn (Integrity)", status_text, help="Kiểm tra quan hệ treo, thiếu định danh hoặc vướng danh mục")

        if problems:
            st.warning(f"⚠️ Có {len(problems)} diagnostics; xem chi tiết để phân biệt lỗi cấu trúc, bằng chứng và lượt trích xuất lỗi.")
            with st.expander(f"📋 Xem chi tiết {len(problems)} cảnh báo toàn vẹn", expanded=False):
                for p in problems:
                    st.markdown(f"- {p}")
        else:
            st.caption("Kiểm tra cấu trúc không xác nhận tính đúng đắn lịch sử của dữ kiện.")

    active_graph_project = snapshot.as_project()
    graph_context_id = f"{proj_id}_{snapshot.fingerprint[:16]}"
    st.caption(f"Graph fingerprint: {snapshot.fingerprint}")

    # =========================================================================
    # PHÂN KHU 2: TÁCH BẠCH KHÁM PHÁ & NGHIÊN CỨU
    # =========================================================================
    tab_qa, tab_export, tab_bench, tab_train_studio = st.tabs(
        [
            "🔍 1. Khám phá & Hỏi đáp (G-Retriever)",
            "📦 2. Bản đồ, Bảng Quan hệ & Xuất tệp",
            "🧪 3. Nghiên cứu: Đối sánh Thuật toán (Benchmark)",
            "🧬 4. Nghiên cứu: Sinh Dữ liệu Huấn luyện (QA Studio)",
        ]
    )

    with tab_qa:
        render_g_retriever_qa_tab(graph_service, active_graph_project, graph_context_id)

    with tab_bench:
        render_benchmark_tab(graph_service, active_graph_project, graph_context_id)

    with tab_train_studio:
        if current_approved:
            render_training_dataset_tab(facade, project, proj_id)
        else:
            st.info("Graph thô dùng để đánh giá; không tự coi observations là nhãn đúng để sinh dữ liệu huấn luyện.")

    with tab_export:
        nodes_by_id = {n["id"]: n for n in nodes}
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
                            help=f"Chỉ giới hạn hiển thị, không cắt dữ liệu xuất ({total_edges} cạnh).",
                        )
                    )
                    st.session_state[limit_state_key] = display_limit
                else:
                    display_limit = total_edges

                displayed_edges = edges[:display_limit]
                displayed_node_ids = {x for e in displayed_edges for x in (e["source"], e["target"])}
                st.caption(
                    f"ℹ️ Đang hiển thị **{len(displayed_edges)}/{total_edges}** cạnh trên sơ đồ minh họa "
                    f"(tương ứng **{len(displayed_node_ids)}/{len(nodes)}** thực thể). "
                    "Giới hạn cạnh hiển thị chỉ áp dụng cho sơ đồ minh họa; mọi tệp xuất bên dưới vẫn giữ đủ toàn bộ dữ liệu của nguồn đang chọn."
                )

                st.graphviz_chart(build_graph_dot([n for n in nodes if n["id"] in displayed_node_ids], displayed_edges))

                with st.expander(
                    f"📋 Bảng quan hệ & Bằng chứng đầy đủ (hỗ trợ bàn phím, {len(edges)} cạnh)",
                    expanded=False,
                ):
                    edge_table_rows = [
                        {
                            "Nguồn": nodes_by_id.get(e.get("source"), {}).get("name", e.get("source", "")),
                            "Quan hệ": e.get("relation", ""),
                            "Đích": nodes_by_id.get(e.get("target"), {}).get("name", e.get("target", "")),
                            "Bằng chứng": e.get("evidence", ""),
                            "Tài liệu": e.get("doc_name", ""),
                        }
                        for e in edges
                    ]
                    st.dataframe(edge_table_rows, width="stretch", hide_index=True)
        else:
            st.info(
                "Nguồn đang chọn chưa có cạnh để hiển thị. Xem lựa chọn runs hoặc diagnostics phía trên."
            )

        st.divider()
        st.markdown(f"#### 💾 Xuất Dữ liệu Đồ thị ({source_selection} — {len(nodes):,} thực thể, {len(edges):,} quan hệ)")

        enriched_edges = []
        for e in edges:
            ec = dict(e)
            src = nodes_by_id.get(e.get("source"), {})
            tgt = nodes_by_id.get(e.get("target"), {})
            ec["source_name"] = src.get("name", "")
            ec["target_name"] = tgt.get("name", "")
            enriched_edges.append(ec)
        std_payload = {
            "project_id": snapshot.project_id,
            "source": snapshot.source,
            "thuc_the": nodes,
            "quan_he": enriched_edges,
        }
        std_json_bytes = json.dumps(std_payload, ensure_ascii=False, indent=2).encode("utf-8")

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "⬇️ Tải JSON Đầy đủ (thuc_the & quan_he)",
                data=std_json_bytes,
                file_name=f"{snapshot.source}_thuc_the_quan_he.json",
                mime="application/json",
                width="stretch",
                key="p05_std_json",
            )
            st.download_button(
                "⬇️ Tải graph đang chọn (JSON + manifest)",
                data=graph_service.export_graph_json(snapshot),
                file_name=f"{snapshot.source}_graph.json",
                mime="application/json",
                width="stretch",
                key="p05_graph_json",
            )
        with dl_col2:
            st.download_button(
                "⬇️ Tải edges/observations (CSV)",
                data=graph_service.csv_bytes(
                    enriched_edges,
                    ["id", "source_name", "relation", "target_name", "evidence", "source", "target", "doc_name", "run_id"],
                ),
                file_name=f"{snapshot.source}_edges.csv",
                mime="text/csv",
                width="stretch",
                key="p05_graph_edges_csv",
            )
            st.download_button(
                "⬇️ Tải danh sách thực thể nodes (CSV)",
                data=graph_service.csv_bytes(nodes, ["id", "name", "kind", "description"]),
                file_name=f"{snapshot.source}_nodes.csv",
                mime="text/csv",
                width="stretch",
                key="p05_nodes_csv",
            )

        if snapshot.diagnostics:
            with st.expander("Diagnostics và mục không dựng được cạnh"):
                st.json(snapshot.diagnostics)
        if not current_approved:
            return
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

            export_key = f"_export_cache_{project.get('project_id', 'default')}_{snapshot.fingerprint}"
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
