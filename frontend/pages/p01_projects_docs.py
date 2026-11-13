"""Màn hình 01: Nguồn Tư liệu & Quản lý Văn bản (Documents).
Theo cấu trúc đề xuất trong KG_Studio/AI/report/layout-pipeline-proposal.md.
"""
from __future__ import annotations

import streamlit as st

from backend.domain.documents.processor import count_chunks
from backend.facade import get_facade
from frontend.components.pipeline_banner import render_step_next_action
from frontend.state.session import navigate_to_step


def render_projects_docs_page(project: dict) -> None:
    facade = get_facade()
    docs = project.get("documents", [])
    proj_key = str(project.get("project_id") or project.get("name") or "default")

    st.subheader(f"📄 1. Tư liệu Nguồn — Dự án: {project.get('name', '')}")
    st.caption(
        "Luồng thao tác: Chọn tệp (.txt, .docx, .pdf) → Đọc & kiểm tra kết quả từng tệp → Rà soát nội dung trước khi trích xuất."
    )

    # 1. HÀNH ĐỘNG GỢI Ý TIẾP THEO (Next Action Callout — nút phụ ở trên)
    render_step_next_action("documents", project)

    # 2. THẺ TIẾP TỤC CÔNG VIỆC (Cho các dự án đang làm dở)
    if docs:
        stats = facade.review_stats(project)
        errors = project.get("chunk_errors", {})

        if errors:
            with st.container(border=True):
                c_w1, c_w2 = st.columns([3.5, 1.5])
                c_w1.warning(f"⚠️ **Có {len(errors)} đoạn văn bản gặp lỗi** ở các lần xử lý trước.")
                if c_w2.button("🔧 Xử lý đoạn lỗi ở Bước 3", width="stretch", key="p01_btn_fix_errors"):
                    navigate_to_step("extraction")
                    st.rerun()
        elif stats["pending"] + stats["check"] > 0:
            with st.container(border=True):
                c_p1, c_p2 = st.columns([3.5, 1.5])
                c_p1.info(f"📋 **Còn {stats['pending']} quan hệ chờ duyệt** và {stats['check']} quan hệ cần kiểm tra.")
                if c_p2.button("🔬 Sang Bước 4 để rà soát", width="stretch", key="p01_btn_goto_review"):
                    navigate_to_step("review")
                    st.rerun()

    # 3. KHU VỰC CHỌN & THÊM TÀI LIỆU MỚI
    st.divider()
    st.markdown("#### 📥 Thêm Tài liệu Mới")
    uploaded = st.file_uploader(
        "Bước A — Chọn tệp văn bản từ máy tính",
        type=["txt", "docx", "pdf"],
        accept_multiple_files=True,
        help="Hỗ trợ tệp văn bản .txt (UTF-8), Word .docx và PDF có lớp văn bản.",
        key=f"p01_uploader_{proj_key}",
    )

    with st.expander("🏷️ Nhãn nguồn & phạm vi tư liệu (tùy chọn)", expanded=False):
        col_a, col_b = st.columns(2)
        scope = col_a.text_input("Phạm vi địa lý / tên di tích", placeholder="Ví dụ: Hoàn Kiếm, Hà Nội")
        source_label = col_b.text_input("Nhãn nguồn tư liệu", placeholder="Ví dụ: Hồ sơ di tích 2024, Sách Lịch sử...")

    if uploaded:
        st.caption(
            f"⏳ Đã chọn **{len(uploaded)} tệp** trên trình duyệt (chưa lưu vào dự án). "
            "Nhấn nút bên dưới để đọc nội dung và thêm vào dự án."
        )
        if st.button("📥 Bước B — Đọc & thêm các tệp đã chọn vào dự án", type="primary", width="stretch", key="p01_btn_ingest_files"):
            report_items: list[dict] = []
            added_count = 0
            for file in uploaded:
                ok, msg = facade.add_document(project, file.name, file.getvalue(), scope, source_label)
                if ok:
                    added_count += 1
                report_items.append({"name": file.name, "ok": ok, "msg": msg})

            if added_count > 0:
                facade.save_project(project)
            st.session_state[f"_p01_upload_report_{proj_key}"] = report_items
            st.rerun()

    upload_report = st.session_state.pop(f"_p01_upload_report_{proj_key}", None)
    if isinstance(upload_report, list) and upload_report:
        ok_items = [r for r in upload_report if r.get("ok")]
        fail_items = [r for r in upload_report if not r.get("ok")]
        with st.container(border=True):
            st.markdown(f"**Kết quả nạp tệp:** {len(ok_items)} thành công · {len(fail_items)} không thêm được")
            for item in upload_report:
                if item.get("ok"):
                    st.success(f"✅ `{item['name']}` — {item['msg']}")
                else:
                    st.error(f"❌ `{item['name']}` — {item['msg']}")

    # 4. DANH SÁCH TÀI LIỆU HIỆN CÓ
    st.divider()
    st.markdown(f"#### 📚 Tài liệu trong Dự án ({len(docs)} tài liệu)")

    if not docs:
        st.info("💡 **Dự án chưa có tài liệu nào.** Hãy chọn ít nhất một tệp ở trên và bấm thêm vào dự án để bắt đầu.")
        return

    table_data = []
    warn_docs = []
    for d in docs:
        raw_text = d.get("text", "")
        has_warnings = bool(d.get("warnings"))
        if has_warnings:
            warn_docs.append(d)
        display_name = f"⚠️ {d['name']}" if has_warnings else d["name"]
        status_txt = f"⚠️ Cần kiểm tra ({len(d.get('warnings', []))} cảnh báo)" if has_warnings else "✅ Hợp lệ"
        table_data.append(
            {
                "Tên tệp": display_name,
                "Trạng thái đọc": status_txt,
                "Nguồn tư liệu": d.get("source_label") or "—",
                "Phạm vi": d.get("place_scope") or "—",
            }
        )

    if warn_docs:
        st.warning(
            f"⚠️ Có **{len(warn_docs)} tài liệu** phát sinh cảnh báo khi đọc nội dung (ví dụ: PDF ít chữ hoặc lỗi định dạng). "
            "Mở mục chi tiết bên dưới để kiểm tra nội dung thực tế."
        )

    st.dataframe(table_data, width="stretch", hide_index=True)

    # 5. CHI TIẾT KỸ THUẬT & XEM TRƯỚC VĂN BẢN ĐÃ ĐỌC
    with st.expander("🔍 Chi tiết tài liệu & Xem trước văn bản đã bóc tách", expanded=bool(warn_docs)):
        doc_names = [d["name"] for d in docs]
        chosen_doc_name = st.selectbox("Chọn tài liệu cần kiểm tra", doc_names, key="p01_sel_doc_preview")
        target_doc = next((d for d in docs if d["name"] == chosen_doc_name), None)
        if target_doc:
            text_preview = target_doc.get("text", "")
            n_chunks = count_chunks(text_preview)
            d_c1, d_c2, d_c3 = st.columns(3)
            d_c1.metric("Độ dài văn bản", f"{len(text_preview):,} ký tự")
            d_c2.metric("Ước tính đoạn văn", f"{n_chunks} đoạn")
            d_c3.metric("Thời gian thêm", str(target_doc.get("created_at", "—"))[:19])

            if target_doc.get("warnings"):
                st.warning(f"⚠️ Phát hiện {len(target_doc['warnings'])} cảnh báo đọc tệp cho `{target_doc['name']}`:")
                for w in target_doc["warnings"]:
                    st.markdown(f"- {w}")

            preview_limit = 3000
            if len(text_preview) > preview_limit:
                st.caption(
                    f"⚠️ Văn bản dài ({len(text_preview):,} ký tự). Khung dưới **chỉ hiển thị {preview_limit:,} ký tự đầu tiên** "
                    "(nội dung đầy đủ vẫn được lưu để trích xuất)."
                )
            st.text_area(
                f"Nội dung văn bản đã đọc (tối đa {preview_limit:,} ký tự đầu)",
                value=text_preview[:preview_limit] + ("\n... [Bị giới hạn hiển thị tại 3,000 ký tự đầu]" if len(text_preview) > preview_limit else ""),
                height=220,
                disabled=True,
                key=f"p01_preview_txt_{target_doc.get('id', chosen_doc_name)}",
            )

    # 6. NÚT CHUYỂN BƯỚC TIẾP THEO
    st.divider()
    c_back, c_next = st.columns([1, 2])
    if c_next.button("➡️ Chuyển sang Bước 2: Thiết lập trích xuất", type="primary", width="stretch", key="p01_btn_next_step"):
        navigate_to_step("setup")
        st.rerun()
