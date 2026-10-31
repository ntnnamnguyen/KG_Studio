"""Màn hình 05: Khai thác Đồ thị Tri thức Đã duyệt & Xuất Dữ liệu (JSON / CSV / ZIP / Neo4j).

Tuân thủ kiến trúc luồng 5 bước quy chuẩn theo layout-pipeline-proposal.md.
"""
from __future__ import annotations

from datetime import datetime
import streamlit as st

from backend.facade import compute_project_revision, get_facade
from frontend.components.pipeline_banner import render_step_next_action
from frontend.state.session import navigate_to_step
from shared.config_loader import CONFIG


def render_graph_export_page(project: dict) -> None:
    facade = get_facade()
    st.subheader("🕸️ 5. Khai thác Đồ thị Tri thức & Xuất Dữ liệu")
    render_step_next_action("explore", project)

    nodes, edges = facade.approved_graph(project)
    problems = facade.validate_integrity(project)

    # =========================================================================
    # PHÂN KHU 1: KHAI THÁC ĐỒ THỊ ĐÃ DUYỆT & BÁO CÁO TOÀN VẸN
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
            st.caption("🔒 Tất cả các bộ ba tri thức đã được kiểm tra tính nhất quán và sẵn sàng phân phối.")

    if edges:
        with st.container(border=True):
            st.markdown("#### 🗺️ Bản đồ Trực quan hóa Đồ thị (Graph Visualization)")
            max_edges = int(CONFIG["graph"]["max_edges"])
            if len(edges) > max_edges:
                st.caption(f"ℹ️ Đang hiển thị {max_edges}/{len(edges)} quan hệ đầu tiên để đảm bảo hiệu năng trình duyệt.")

            nodes_by_id = {n["id"]: n["name"] for n in nodes}
            dot_lines = [
                "digraph KG {",
                '  rankdir="LR";',
                '  node [shape=box, style="rounded,filled", fillcolor="#eef6ff", color="#3b82f6", fontname="sans-serif"];',
                '  edge [fontname="sans-serif", color="#64748b", fontsize=10];',
            ]
            for e in edges[:max_edges]:
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

    # =========================================================================
    # PHÂN KHU 2: XUẤT DỮ LIỆU & SAO LƯU (ON-DEMAND EXPORT)
    # =========================================================================
    st.divider()
    with st.container(border=True):
        st.markdown("#### 📦 Tải xuống Bộ dữ liệu Tri thức")
        st.caption(
            "Cơ chế tạo tệp xuất theo yêu cầu (On-demand) giúp tiết kiệm bộ nhớ RAM và bảo toàn cấu trúc dữ liệu chuẩn."
        )

        # Thông tin phạm vi xuất bản
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
                if st.button("🔨 Chuẩn bị Gói Sao lưu ZIP (JSON + CSV)", width="stretch", key="btn_prep_zip"):
                    with st.spinner("Đang nén gói ZIP..."):
                        exp_cache["zip_bytes"] = facade.export_zip(project)
                    st.rerun()
            else:
                st.download_button(
                    "⬇️ Tải Gói Sao lưu ZIP Đầy đủ (JSON + CSV)",
                    data=exp_cache["zip_bytes"],
                    file_name=f"{project.get('name', 'kg_studio')}_export.zip",
                    mime="application/zip",
                    width="stretch",
                    key="btn_dl_zip",
                )
                if st.button("🔄 Làm mới gói ZIP", width="stretch", key="btn_clear_zip"):
                    exp_cache.pop("zip_bytes", None)
                    st.rerun()

    # =========================================================================
    # PHÂN KHU 3: TÍCH HỢP CƠ SỞ DỮ LIỆU ĐỒ THỊ NEO4J (EXPANDER)
    # =========================================================================
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
