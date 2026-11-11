"""Tab 3: Khử trùng cạnh lặp theo bộ ba (Simple Graph / Triple Deduplication)."""
from __future__ import annotations

import streamlit as st

from backend.domain.curation.service import compute_apparent_duplicate_edge_groups
from frontend.client import FrontendClient


def render_triple_dedup_tab(
    project: dict,
    client: FrontendClient,
) -> None:
    """Nội dung Tab 3: Khử trùng cạnh lặp theo bộ ba (Simple Graph / Triple Deduplication)."""
    st.markdown("### ✨ 3. Khử trùng Cạnh Lặp theo Bộ Ba (Triple Deduplication)")
    st.caption(
        "Chuẩn hóa đa đồ thị (Multigraph) về đơn đồ thị: Tự động gom các cạnh có cùng bộ ba "
        "`(Nguồn – Quan hệ – Đích)`, dồn 100% bằng chứng nguyên văn, chuyển hướng ID cũ (`edge_redirects`) và xóa cạnh thừa."
    )

    dup_groups = compute_apparent_duplicate_edge_groups(project.get("edges", []))
    if dup_groups:
        total_dup_edges = sum(g.get("count", 1) - 1 for g in dup_groups)
        with st.container(border=True):
            col_msg, col_btn = st.columns([2, 1.2])
            col_msg.warning(
                f"⚠️ Đang có **{len(dup_groups)}** nhóm bộ ba có cạnh trùng lặp, "
                f"tương ứng **{total_dup_edges}** cạnh bị dư thừa cần hợp nhất."
            )
            if col_btn.button(
                f"⚡ Hợp nhất ngay {total_dup_edges} cạnh trùng lặp (Dồn bằng chứng an toàn)",
                type="primary",
                width="stretch",
                key="btn_collapse_dup_edges_tab3",
                help="Giữ lại cạnh chuẩn nhất cho từng bộ ba, dồn toàn bộ bằng chứng nguyên văn và xóa các cạnh dư thừa.",
            ):
                res = client.collapse_duplicate_edges(project)
                st.success(f"Đã hợp nhất thành công {res.merged_duplicate_edges} cạnh trùng bộ ba!")
                st.rerun()

            st.markdown("##### 📋 Chi tiết các nhóm cạnh đang bị trùng bộ ba:")
            nodes = project.get("nodes", [])
            node_map = {str(n["id"]): str(n.get("name") or n.get("id")) for n in nodes if n.get("id")}
            st.dataframe(
                [
                    {
                        "Thực thể Nguồn": node_map.get(str(g.get("source")), str(g.get("source"))),
                        "Quan hệ": g.get("relation", ""),
                        "Thực thể Đích": node_map.get(str(g.get("target")), str(g.get("target"))),
                        "Số cạnh trùng": g.get("count", 0),
                        "Danh sách ID cạnh": ", ".join(str(x) for x in g.get("edge_ids", [])),
                        "Trạng thái các cạnh": ", ".join(str(s) for s in g.get("statuses", [])),
                    }
                    for g in dup_groups
                ],
                width="stretch",
                hide_index=True,
            )
    else:
        st.success("✅ Đồ thị tri thức sạch sẽ! Hiện tại không phát hiện cạnh nào bị trùng lặp cả 3 thành phần (Nguồn – Quan hệ – Đích).")

    # Hiển thị lịch sử các lần khử trùng cạnh
    hist = [h for h in project.get("curation_history", []) if h.get("action") == "collapse_duplicate_edges"]
    edge_redirects = project.get("edge_redirects", {})
    with st.expander(f"📜 Lịch sử Khử trùng Cạnh Lặp ({len(hist)} phiên) & Ánh xạ Cạnh ({len(edge_redirects)} chuyển hướng)", expanded=False):
        if edge_redirects:
            st.caption("Bảng ánh xạ phẳng `edge_redirects` (`old_edge_id -> canonical_edge_id`):")
            st.json(edge_redirects)
        if hist:
            st.dataframe(
                [
                    {
                        "Mã phiên": h.get("id", ""),
                        "Thời điểm": h.get("at", ""),
                        "Người thực hiện": h.get("actor", ""),
                        "Số cạnh đã khử": h.get("dropped_count", 0),
                        "Ghi chú": h.get("note", ""),
                    }
                    for h in reversed(hist)
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Chưa có phiên khử trùng cạnh lặp thủ công nào được ghi nhận.")
