"""Component hiển thị chi tiết từng bước (Step Traces) của quy trình EDC + R."""
from __future__ import annotations

import streamlit as st


def render_step_traces(run: dict) -> None:
    # 1. Thẻ Provenance Nguồn gốc Prompt & Request đã chạy
    ver_id = run.get("prompt_version_id")
    req_hash = run.get("prepared_request_hash")
    c_hash = run.get("prompt_content_hash")
    if ver_id or req_hash:
        with st.container(border=True):
            p1, p2, p3 = st.columns(3)
            p1.write(f"🏷️ **Phiên bản Prompt**: `{ver_id or 'legacy'}`")
            if c_hash:
                p2.write(f"🔢 **Prompt Hash**: `{c_hash[:12]}`")
            if req_hash:
                p3.write(f"🔒 **Request Hash**: `{req_hash[:12]}`")

    prep_req = run.get("prepared_request")
    if isinstance(prep_req, dict) and prep_req.get("system_prompt"):
        with st.expander("👁️ Nội dung Request Thực tế đã Gửi tới LLM trong Lượt này", expanded=False):
            st.caption("Truy vết chính xác system/user prompt được pin tại thời điểm thực thi.")
            t1, t2 = st.tabs(["System Prompt Đã gửi", "User Message Đã gửi"])
            with t1:
                st.code(prep_req.get("system_prompt", ""), language="markdown")
            with t2:
                st.code(prep_req.get("user_message", ""), language="markdown")

    traces = run.get("step_traces") or []
    if not traces:
        return

    st.markdown("**🔍 Nhật ký từng bước của Engine (Step Traces):**")
    for idx, trace in enumerate(traces, 1):
        step_name = trace.get("step_name", f"Bước {idx}")
        loop_idx = trace.get("loop_index", 1)
        dur = trace.get("duration_ms", 0)
        summary = trace.get("summary", "")
        details = trace.get("details") or {}

        st.markdown(f"- **Vòng {loop_idx} · {step_name}** ({dur} ms): {summary}")
        if details:
            with st.expander(f"Chi tiết kỹ thuật — {step_name} (Vòng {loop_idx})", expanded=False):
                st.json(details)

