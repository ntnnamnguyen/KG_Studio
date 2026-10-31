"""Màn hình 01: Nguồn Tư liệu & Quản lý Văn bản (Documents).
Theo cấu trúc đề xuất trong KG_Studio/AI/report/layout-pipeline-proposal.md.
"""
from __future__ import annotations

import streamlit as st

from backend.domain.documents.processor import count_chunks
from backend.facade import get_facade
from frontend.components.pipeline_banner import render_step_next_action
from frontend.state.session import compute_pipeline_readiness, navigate_to_step


def render_projects_docs_page(project: dict) -> None:
    facade = get_facade()
    docs = project.get("documents", [])
    readiness = compute_pipeline_readiness(project)

    st.subheader(f"📄 1. Nguồn Tư liệu & Quản lý Văn bản — Dự án: {project.get('name', '')}")
    st.caption("Quản lý tài liệu nguồn (.txt, .docx, .pdf), kiểm tra chất lượng văn bản đã bóc tách trước khi trích xuất.")

    # 1. HÀNH ĐỘNG GỢI Ý TIẾP THEO (Next Action Callout)
    render_step_next_action("documents", project)

    # 2. THẺ TIẾP TỤC CÔNG VIỆC (Cho các dự án đang làm dở)
    if docs:
        stats = facade.review_stats(project)
        errors = project.get("chunk_errors", {})
        runs = project.get("runs", [])

        if errors:
            with st.container(border=True):
                c_w1, c_w2 = st.columns([3.5, 1.5])
                c_w1.warning(f"⚠️ **Có {len(errors)} đoạn văn bản gặp lỗi** trong các lượt trích xuất trước đó.")
                if c_w2.button("🔧 Xử lý đoạn lỗi ở Bước 3", width="stretch", key="p01_btn_fix_errors"):
                    navigate_to_step("extraction")
                    st.rerun()
        elif stats["pending"] + stats["check"] > 0:
            with st.container(border=True):
                c_p1, c_p2 = st.columns([3.5, 1.5])
                c_p1.info(f"📋 **Còn {stats['pending']} quan hệ chờ duyệt** và {stats['check']} quan hệ cần kiểm tra.")
                if c_p2.button("🔬 Sang Bước 4 để duyệt dữ kiện", width="stretch", key="p01_btn_goto_review"):
                    navigate_to_step("review")
                    st.rerun()

    # 3. KHU VỰC TẢI LÊN TÀI LIỆU
    st.divider()
    st.markdown("#### 📥 Thêm Tài liệu Mới")
    uploaded = st.file_uploader(
        "Kéo thả hoặc chọn tệp văn bản từ máy tính",
        type=["txt", "docx", "pdf"],
        accept_multiple_files=True,
        help="Hỗ trợ tệp văn bản .txt (UTF-8), tài liệu Word .docx và tài liệu PDF có lớp văn bản.",
    )

    with st.expander("🏷️ Thông tin nguồn & phạm vi tư liệu (tùy chọn)", expanded=False):
        col_a, col_b = st.columns(2)
        scope = col_a.text_input("Phạm vi địa lý / tên di tích", placeholder="Ví dụ: Hoàn Kiếm, Hà Nội")
        source_label = col_b.text_input("Nhãn nguồn tư liệu", placeholder="Ví dụ: Hồ sơ di tích 2024, Sách Lịch sử...")

    if uploaded and st.button("📥 Nạp các tệp đã chọn vào dự án", type="primary", width="stretch"):
        added_count = 0
        for file in uploaded:
            ok, msg = facade.add_document(project, file.name, file.getvalue(), scope, source_label)
            if ok:
                added_count += 1
                st.success(msg)
            else:
                st.warning(msg)
        if added_count:
            facade.save_project(project)
            st.rerun()

    # 4. DANH SÁCH TÀI LIỆU HIỆN CÓ
    st.divider()
    st.markdown(f"#### 📚 Danh mục Tài liệu trong Dự án ({len(docs)} tài liệu)")

    if not docs:
        st.info("💡 **Dự án chưa có tài liệu nào.** Hãy tải lên ít nhất một tệp văn bản ở trên để bắt đầu xây dựng đồ thị tri thức.")
        return

    # Thống kê nhanh
    total_chars = sum(int(d.get("chars", len(d.get("text", "")))) for d in docs)
    st.caption(f"Tổng dung lượng văn bản: **{total_chars:,} ký tự** · Định dạng: {', '.join(sorted({d['name'].split('.')[-1].upper() for d in docs}))}")

    table_data = []
    for d in docs:
        raw_text = d.get("text", "")
        n_chunks = count_chunks(raw_text)
        has_warnings = bool(d.get("warnings"))
        status_txt = "⚠️ Cần kiểm tra" if has_warnings else "✅ Hợp lệ"
        table_data.append(
            {
                "Tên tệp": d["name"],
                "Ký tự": f"{len(raw_text):,}",
                "Ước tính đoạn": n_chunks,
                "Trạng thái": status_txt,
                "Phạm vi": d.get("place_scope", "—"),
                "Nguồn": d.get("source_label", "—"),
                "Thời gian thêm": str(d.get("created_at", ""))[:19],
            }
        )

    st.dataframe(table_data, width="stretch", hide_index=True)

    # 5. XEM TRƯỚC VĂN BẢN ĐÃ ĐỌC (Text Inspector)
    with st.expander("🔍 Xem trước nội dung văn bản đã bóc tách từ tài liệu", expanded=False):
        doc_names = [d["name"] for d in docs]
        chosen_doc_name = st.selectbox("Chọn tài liệu cần xem", doc_names, key="p01_sel_doc_preview")
        target_doc = next((d for d in docs if d["name"] == chosen_doc_name), None)
        if target_doc:
            if target_doc.get("warnings"):
                st.warning("Cảnh báo khi đọc file:\n- " + "\n- ".join(target_doc["warnings"]))
            text_preview = target_doc.get("text", "")
            st.text_area(
                "Nội dung văn bản (đầu 3,000 ký tự)",
                value=text_preview[:3000] + ("\n... [Còn tiếp]" if len(text_preview) > 3000 else ""),
                height=220,
                disabled=True,
            )

    # 6. NÚT CHUYỂN BƯỚC TIẾP THEO
    st.divider()
    c_back, c_next = st.columns([1, 2])
    if c_next.button("➡️ Chuyển sang Bước 2: Thiết lập trích xuất", type="primary", width="stretch", key="p01_btn_next_step"):
        navigate_to_step("setup")
        st.rerun()
