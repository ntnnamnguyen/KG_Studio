"""Màn hình 05: Khai thác Đồ thị Tri thức (G-Retriever & GraphRAG Lab) & Xuất Dữ liệu (JSON / CSV / ZIP / Neo4j).

Tuân thủ kiến trúc luồng 5 bước quy chuẩn theo layout-pipeline-proposal.md.
Tích hợp trực tiếp phòng thí nghiệm G-Retriever (PCST), HippoRAG (PPR) và Bộ Benchmark Thực nghiệm Đối sánh.
"""
from __future__ import annotations

from typing import Any
import streamlit as st

from backend.facade import compute_project_revision, get_facade
from frontend.components.export_tabs import (
    build_subgraph_dot,
    format_benchmark_csv,
    format_benchmark_markdown,
    render_benchmark_tab,
    render_g_retriever_qa_tab,
    render_gretriever_bundle_studio,
    render_training_dataset_tab,
)
from frontend.components.pipeline_banner import render_step_next_action
from frontend.components.graph_source import select_graph_snapshot
from frontend.components.graph_view import build_graph_dot
from frontend.composition import get_ui_composition
from frontend.state.session import (
    bump_sync_nonce,
    navigate_to_step,
    prepare_curation_edges_recheck,
    sync_keyed_int,
    sync_keyed_value,
)
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

    composition = get_ui_composition()
    graph_service = composition.graph_qa_service
    curation_service = composition.curation_service
    selected = select_graph_snapshot(project, graph_service)
    if selected is None:
        return
    snapshot, source_selection = selected
    current_approved = source_selection == "approved"
    nodes, edges = snapshot.nodes, snapshot.edges
    if current_approved:
        if hasattr(graph_service, "inspect_integrity"):
            integrity_report = graph_service.inspect_integrity(project)
            problems = integrity_report.get("problems", [])
            invalid_approved_ids = integrity_report.get("invalid_approved_edge_ids", [])
        else:
            problems = graph_service.validate_integrity(project)
            invalid_approved_ids = []
    else:
        problems = [
            f"{item.get('code')} · run {item.get('run_id', '')} · triple {item.get('triple_index', '')}"
            for item in snapshot.diagnostics
        ]
        invalid_approved_ids = []
    proj_id = str(project.get("project_id", "default"))

    reopen_notice_key = f"_p05_reopen_notice_{proj_id}"
    reopen_notice = st.session_state.get(reopen_notice_key)
    if isinstance(reopen_notice, dict):
        if reopen_notice.get("revision") == compute_project_revision(project) and int(reopen_notice.get("count") or 0) > 0:
            n_col1, n_col2 = st.columns([3.0, 1.4])
            n_col1.success(
                f"✅ Đã đưa {int(reopen_notice['count'])} cạnh đã duyệt bị lỗi về trạng thái 'Cần kiểm tra'."
            )
            if n_col2.button(
                "🔍 Mở Trang 4 xử lý ngay",
                key=f"p05_go_curation_recheck_{proj_id}",
                width="stretch",
            ):
                st.session_state.pop(reopen_notice_key, None)
                navigate_to_step("review")
                st.rerun()
        else:
            st.session_state.pop(reopen_notice_key, None)

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
            if current_approved and invalid_approved_ids:
                st.warning(
                    f"⚠️ Có {len(problems)} cảnh báo trên {len(invalid_approved_ids)} cạnh Đã duyệt đang bị lỗi; "
                    "xem chi tiết hoặc đưa về 'Cần kiểm tra' để xử lý."
                )
            else:
                st.warning(
                    f"⚠️ Có {len(problems)} cảnh báo / diagnostics; "
                    "xem chi tiết để phân biệt lỗi cấu trúc, bằng chứng và lượt trích xuất lỗi."
                )
            if current_approved and invalid_approved_ids:
                if st.button(
                    f"↩️ Đưa {len(invalid_approved_ids)} cạnh đã duyệt bị lỗi về 'Cần kiểm tra'",
                    key=f"p05_btn_reopen_invalid_approved_{proj_id}",
                    type="primary",
                    help="Chuyển các cạnh Đã duyệt đang bị lỗi toàn vẹn về trạng thái 'Cần kiểm tra' để xác nhận lại ở Trang 4.",
                ):
                    try:
                        res = curation_service.reopen_edges_for_review(
                            project,
                            invalid_approved_ids,
                            expected_revision=compute_project_revision(project),
                        )
                        prepare_curation_edges_recheck(project, res.applied_ids)
                        bump_sync_nonce("_inspector_action_nonce")
                        st.session_state[reopen_notice_key] = {
                            "count": res.applied_count,
                            "revision": res.revision_after,
                        }
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Không thể đưa cạnh về 'Cần kiểm tra': {exc}")
            with st.expander(f"📋 Xem chi tiết {len(problems)} cảnh báo toàn vẹn", expanded=False):
                for p in problems:
                    st.markdown(f"- {p}")
        else:
            st.caption("Kiểm tra cấu trúc không xác nhận tính đúng đắn lịch sử của dữ kiện.")

    active_graph_project = snapshot.as_project()
    graph_context_id = f"{proj_id}_{snapshot.fingerprint[:16]}"
    st.caption(f"Graph fingerprint: {snapshot.fingerprint}")

    # =========================================================================
    # PHÂN KHU 2: TÁCH BẠCH KHÁM PHÁ & NGHIÊN CỨU (4 TAB TINH GỌN)
    # =========================================================================
    tab_qa, tab_export, tab_bench, tab_gret_5files = st.tabs(
        [
            "🔍 1. Khám phá & Hỏi đáp (G-Retriever)",
            "📦 2. Bản đồ, Bảng Quan hệ & Xuất tệp",
            "🧪 3. Nghiên cứu: Đối sánh Thuật toán (Benchmark)",
            "🎯 4. Xuất Chuẩn G-Retriever (5 Tệp)",
        ]
    )

    with tab_qa:
        render_g_retriever_qa_tab(graph_service, active_graph_project, graph_context_id)

    with tab_bench:
        render_benchmark_tab(graph_service, active_graph_project, graph_context_id)

    with tab_gret_5files:
        if current_approved:
            render_gretriever_bundle_studio(
                graph_service,
                project,
                proj_id=proj_id,
                fingerprint=snapshot.fingerprint,
                approved_only=True,
            )
        else:
            st.info("Chuyển nguồn đồ thị sang `approved` để tạo và xuất Bộ 5 Tệp Chuẩn G-Retriever từ dữ liệu đã kiểm duyệt.")

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
                    slider_nonce_key = f"_p06_slider_nonce_{proj_id}"

                    ctrl_c1, ctrl_c2 = st.columns([4, 1], vertical_alignment="bottom")
                    if ctrl_c2.button(
                        f"🚀 Tối đa ({total_edges})",
                        width="stretch",
                        key=f"p06_btn_max_edges_{proj_id}",
                        help="Đặt thanh trượt lên số lượng cạnh tối đa hiện có.",
                    ):
                        clamped_limit = total_edges
                        st.session_state[limit_state_key] = total_edges
                        bump_sync_nonce(slider_nonce_key)
                        st.rerun()

                    slider_nonce = int(st.session_state.get(slider_nonce_key) or 0)
                    sync_keyed_int(
                        slider_key,
                        clamped_limit,
                        (proj_id, total_edges, slider_nonce),
                        min_value=1,
                        max_value=total_edges,
                    )
                    # Trong bare mode (không có ScriptRunContext, vd: unit test gọi thẳng render page),
                    # widget Streamlit bỏ qua session_state nên cần truyền value= fallback.
                    from streamlit.runtime.scriptrunner import get_script_run_ctx

                    slider_kwargs = {"value": clamped_limit} if get_script_run_ctx(suppress_warning=True) is None else {}
                    display_limit = int(
                        ctrl_c1.slider(
                            "🎚️ Kéo để tăng/giảm số lượng cạnh hiển thị",
                            min_value=1,
                            max_value=total_edges,
                            step=1,
                            key=slider_key,
                            help=f"Chỉ giới hạn hiển thị, không cắt dữ liệu xuất ({total_edges} cạnh).",
                            **slider_kwargs,
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

        dl_col1, dl_col2, dl_col3 = st.columns(3)
        with dl_col1:
            st.download_button(
                "⬇️ Tải Đồ thị JSON (Nodes, Edges & Manifest)",
                data=graph_service.export_graph_json(snapshot),
                file_name=f"{snapshot.source}_graph.json",
                mime="application/json",
                width="stretch",
                key="p05_graph_json",
            )
        with dl_col2:
            st.download_button(
                "⬇️ Tải Danh sách Thực thể (nodes.csv)",
                data=graph_service.csv_bytes(nodes, ["id", "name", "kind", "description"]),
                file_name=f"{snapshot.source}_nodes.csv",
                mime="text/csv",
                width="stretch",
                key="p05_nodes_csv",
            )
        with dl_col3:
            st.download_button(
                "⬇️ Tải Danh sách Quan hệ (edges.csv)",
                data=graph_service.csv_bytes(
                    enriched_edges,
                    ["id", "source_name", "relation", "target_name", "evidence", "source", "target", "doc_name", "run_id"],
                ),
                file_name=f"{snapshot.source}_edges.csv",
                mime="text/csv",
                width="stretch",
                key="p05_graph_edges_csv",
            )

        if snapshot.diagnostics:
            with st.expander("Diagnostics và mục không dựng được cạnh"):
                st.json(snapshot.diagnostics)
        if not current_approved:
            return

        with st.expander("🗄️ Tích hợp Cơ sở dữ liệu Đồ thị Neo4j (Tùy chọn nâng cao)", expanded=False):
            st.caption("Đẩy trực tiếp các thực thể và quan hệ đã duyệt vào cơ sở dữ liệu Neo4j qua giao thức Bolt.")
            n1, n2, n3, n4 = st.columns(4)
            sync_keyed_value("p06_neo4j_uri", CONFIG["neo4j"]["uri"], "init")
            sync_keyed_value("p06_neo4j_user", CONFIG["neo4j"]["username"], "init")
            sync_keyed_value("p06_neo4j_db", CONFIG["neo4j"]["database"], "init")
            uri = n1.text_input("Neo4j URI", key="p06_neo4j_uri")
            user = n2.text_input("Username", key="p06_neo4j_user")
            password = n3.text_input("Password", type="password", key="p06_neo4j_pwd")
            database = n4.text_input("Database", key="p06_neo4j_db")

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
