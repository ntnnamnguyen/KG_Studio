"""Component hiển thị Tiến trình Quy trình 5 bước và Thẻ Hành động Tiếp theo (Pipeline Banner & Next Action).
Tuân thủ thiết kế hướng dẫn trong KG_Studio/AI/report/layout-pipeline-proposal.md.
"""
from __future__ import annotations

from typing import Any
import streamlit as st

from frontend.state.session import (
    PAGE_LABELS,
    PIPELINE_STEPS,
    compute_pipeline_readiness,
    get_active_step,
    navigate_to_step,
)


_BADGE_TEXT = {
    "✓": "✓ Sẵn sàng",
    "●": "● Đang chờ",
    "!": "! Cần chú ý",
    "○": "○ Chưa làm",
}


def render_pipeline_header(project: dict) -> None:
    """Hiển thị thanh tóm tắt dự án, bước hiện tại và tiến độ 5 bước (Sidebar là điều hướng chính)."""
    active_step_id, active_idx, active_label = get_active_step()
    readiness = compute_pipeline_readiness(project)
    proj_name = str(project.get("name") or "Chưa đặt tên")
    mode = str(project.get("extraction_mode") or "closed")

    with st.container(border=True):
        c_title, c_step = st.columns([2.2, 1.8])
        c_title.markdown(f"📁 **Dự án:** `{proj_name}` &nbsp;·&nbsp; ⚙️ Phương pháp: `{mode}`")
        c_step.markdown(f"🧭 **Bước hiện tại ({active_idx + 1}/5):** `{active_label}`")

        step_chips: list[str] = []
        for idx, (step_id, label) in enumerate(zip(PIPELINE_STEPS, PAGE_LABELS)):
            badge = readiness.get(step_id, {}).get("badge", "○")
            step_title = label.split(". ", 1)[-1]
            status_lbl = _BADGE_TEXT.get(badge, badge)
            if idx == active_idx:
                step_chips.append(f"**[{idx + 1}. {step_title}: {status_lbl}]**")
            else:
                step_chips.append(f"{idx + 1}. {step_title}: {status_lbl}")
        st.caption(" · ".join(step_chips))


def render_step_next_action(current_step_id: str, project: dict) -> None:
    """Hiển thị thẻ gợi ý hành động tiếp theo theo đúng ngữ cảnh của bước hiện tại."""
    readiness = compute_pipeline_readiness(project)
    active_step_id, active_idx, _ = get_active_step()

    # Cấu hình hành động cho từng bước
    step_actions = {
        "documents": {
            "title": "Thiết lập cấu hình trích xuất",
            "desc": f"Đã có {readiness['documents']['count']} tài liệu ({readiness['documents']['total_chars']:,} ký tự) sẵn sàng.",
            "target_step": "setup",
            "btn_text": "➡️ Chuyển sang Bước 2: Thiết lập trích xuất",
            "condition": readiness["documents"]["count"] > 0,
            "warn_text": "⚠️ Chưa có tài liệu nào trong dự án. Hãy tải lên ít nhất một tệp .txt, .docx, hoặc .pdf để tiếp tục.",
        },
        "setup": {
            "title": "Tiến hành trích xuất tri thức",
            "desc": f"Chế độ: '{readiness['setup']['mode']}', danh mục và kết nối mô hình đã sẵn sàng.",
            "target_step": "extraction",
            "btn_text": "➡️ Chuyển sang Bước 3: Trích xuất tri thức",
            "condition": readiness["documents"]["count"] > 0 and readiness["setup"]["ready"],
            "warn_text": "⚠️ Cần có ít nhất 1 tài liệu ở Bước 1 trước khi bắt đầu trích xuất.",
        },
        "extraction": {
            "title": "Rà soát & Kiểm duyệt tri thức",
            "desc": (
                f"Đã xử lý {readiness['extraction']['runs_count']} lượt trích xuất. "
                + (f"Phát hiện {readiness['extraction']['errors_count']} đoạn gặp lỗi cần xử lý." if readiness['extraction']['errors_count'] > 0 else "Sẵn sàng kiểm duyệt.")
            ),
            "target_step": "review",
            "btn_text": "➡️ Chuyển sang Bước 4: Rà soát & Chuẩn hóa",
            "condition": readiness["extraction"]["runs_count"] > 0 or readiness["review"]["needs_review_count"] > 0,
            "warn_text": "ℹ️ Chưa chạy lượt trích xuất nào. Hãy chọn tài liệu bên dưới và nhấn 'Bắt đầu trích xuất'.",
        },
        "review": {
            "title": "Khai thác đồ thị & Xuất dữ liệu",
            "desc": (
                f"Đã duyệt {readiness['review']['approved_count']} dữ kiện. "
                + (f"Còn {readiness['review']['needs_review_count']} mục cần xử lý." if readiness['review']['needs_review_count'] > 0 else "Toàn bộ dữ kiện đã chuẩn hóa!")
            ),
            "target_step": "explore",
            "btn_text": "➡️ Chuyển sang Bước 5: Khai thác & Xuất đồ thị",
            "condition": readiness["explore"]["approved_count"] > 0,
            "warn_text": "ℹ️ Chưa có dữ kiện nào được duyệt (Trạng thái 'Đã duyệt'). Hãy duyệt ít nhất một quan hệ để xem đồ thị.",
        },
        "explore": {
            "title": "Thêm tài liệu nghiên cứu mới",
            "desc": f"Đồ thị hiện có {readiness['explore']['nodes_count']} thực thể và {readiness['explore']['edges_count']} quan hệ ({readiness['explore']['approved_count']} đã duyệt).",
            "target_step": "documents",
            "btn_text": "➕ Bổ sung thêm tài liệu ở Bước 1",
            "condition": True,
            "warn_text": "",
        },
    }

    action_info = step_actions.get(current_step_id)
    if not action_info:
        return

    with st.container(border=True):
        c_info, c_btn = st.columns([3.5, 1.5])
        if action_info["condition"]:
            c_info.markdown(f"🎯 **Gợi ý bước tiếp theo**: {action_info['title']} — *{action_info['desc']}*")
            if c_btn.button(
                action_info["btn_text"],
                width="stretch",
                type="secondary",
                key=f"btn_next_action_{current_step_id}",
            ):
                navigate_to_step(action_info["target_step"])
                st.rerun()
        else:
            c_info.caption(action_info["warn_text"])
            c_btn.button(action_info["btn_text"], width="stretch", disabled=True, key=f"btn_next_action_dis_{current_step_id}")

