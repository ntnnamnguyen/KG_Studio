"""Ngăn kéo chi tiết (Detail Drawer) và xử lý đơn cho một đề xuất EDC."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.domain.catalogs.service import is_proposal_candidates_stale, proposal_impact
from frontend.client import get_client
from frontend.state.session import get_edc_table_state
from shared.catalog_utils import relation_catalog
from .logic import status_label_vn, verification_badge_label


def _render_proposal_observations_and_candidates(project: dict, proposal: dict) -> list[dict]:
    """Hiển thị quan sát nguồn, đoạn văn bản chunk gốc và Top-K ứng viên đích."""
    obs = proposal.get("observations") or []
    if obs:
        st.markdown("##### 📄 Nguồn & Bằng chứng quan sát")
        st.dataframe(
            [
                {
                    "Tài liệu": o.get("doc_name") or o.get("doc_id", ""),
                    "Đoạn (Chunk)": o.get("chunk_number", ""),
                    "Ví dụ": o.get("example", ""),
                    "Trích dẫn bằng chứng": o.get("evidence", ""),
                    "Định nghĩa quan sát": o.get("definition", ""),
                }
                for o in obs
            ],
            width='stretch',
            hide_index=True,
        )

        with st.expander("🔍 Đọc Đoạn văn bản Chunk gốc của các Quan sát", expanded=False):
            from frontend.components.merge.provenance_view import get_chunk_info, highlight_text_html
            for o_idx, o in enumerate(obs[:4], 1):
                doc_id = str(o.get("doc_id", ""))
                chunk_num = o.get("chunk_number")
                chunk_info = get_chunk_info(project, doc_id, chunk_num)
                doc_name = o.get("doc_name") or (chunk_info.get("doc_name") if chunk_info else doc_id)
                page_str = f" · Trang {chunk_info['page_from']}" if chunk_info and chunk_info.get("page_from") is not None else ""
                st.caption(f"**Quan sát #{o_idx}:** Tệp `{doc_name}` · Đoạn **{chunk_num or 1}**{page_str}")
                ev_text = str(o.get("evidence") or o.get("example") or proposal.get("name", "")).strip()
                if chunk_info and chunk_info.get("text"):
                    h_html = highlight_text_html(chunk_info["text"], [ev_text, proposal.get("name", "")])
                    st.markdown(h_html, unsafe_allow_html=True)
                elif ev_text:
                    st.info(f"Trích dẫn: {ev_text}")

    cands = proposal.get("alignment_candidates") or []
    if cands:
        st.markdown("##### 🎯 Top-K Ứng viên đích (Target Alignment)")
        st.dataframe(
            [
                {
                    "Ứng viên đích": c.get("name", ""),
                    "Điểm tương đồng": f"{float(c.get('score', 0.0)):.4f}",
                    "Định nghĩa đích": c.get("definition", ""),
                    "Lý do": c.get("reason", ""),
                }
                for c in cands
            ],
            width='stretch',
            hide_index=True,
        )
    else:
        st.caption("Chưa có ứng viên gợi ý cho mục này.")
    return cands


def _render_single_proposal_decision_form(
    project: dict,
    client: Any,
    kind: str,
    proposal: dict,
    pid: str,
    cands: list[dict],
) -> None:
    """Hiển thị form xử lý quyết định đơn (merge / approve / reject) cho một đề xuất."""
    st.markdown("##### ⚡ Xử lý đơn cho riêng mục này (Luồng đơn)")
    action_key = f"single_act_{kind}_{pid}"
    single_action = st.radio(
        "Quyết định đơn",
        ["merge", "approve", "reject"],
        format_func=lambda a: {
            "merge": "Hợp nhất vào mục có sẵn",
            "approve": "Duyệt thành mục mới",
            "reject": "Từ chối đề xuất",
        }[a],
        horizontal=True,
        key=action_key,
    )
    target_options = (
        [r["name"] for r in relation_catalog(project)]
        if kind == "relations"
        else [t["name"] for t in project.get("entity_types", [])]
    )
    best_cand = str(cands[0].get("name", "")) if cands else ""

    if single_action == "merge":
        default_idx = target_options.index(best_cand) if best_cand in target_options else 0
        s_canon = st.selectbox(
            "Chọn mục đích trong danh mục",
            target_options if target_options else [""],
            index=default_idx if target_options else 0,
            key=f"single_merge_t_{kind}_{pid}",
        )
        s_def = str(proposal.get("definition", ""))
        s_desc = ""
    elif single_action == "approve":
        s_canon = st.text_input("Tên chuẩn mới", value=str(proposal.get("name", "")), key=f"single_app_n_{kind}_{pid}")
        s_def = st.text_area("Định nghĩa", value=str(proposal.get("definition", "")), key=f"single_app_d_{kind}_{pid}")
        s_desc = st.text_input("Mô tả", value=str(proposal.get("description", "")), key=f"single_app_desc_{kind}_{pid}")
    else:
        s_canon = ""
        s_def = str(proposal.get("definition", ""))
        s_desc = ""

    s_note = st.text_input("Ghi chú kiểm duyệt", value=str(proposal.get("review_note", "")), key=f"single_note_{kind}_{pid}")
    if st.button("✅ Áp dụng quyết định đơn cho mục này", key=f"btn_single_apply_{kind}_{pid}"):
        try:
            imp = client.decide_single_proposal(project, pid, single_action, s_canon, s_def, s_note, s_desc)
            t_state = get_edc_table_state(project, kind)
            t_state["selected_ids"] = [x for x in t_state["selected_ids"] if x != pid]
            t_state["drafts"].pop(pid, None)
            t_state["flash_messages"].append(
                f"Đã xử lý đơn đề xuất `{proposal.get('name', '')}` ({len(imp['nodes'])} node, {len(imp['edges'])} cạnh ảnh hưởng)."
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def render_proposal_detail_drawer(
    project: dict,
    kind: str,
    proposal: dict,
    *,
    current_model_fingerprint: str = "",
) -> None:
    """Hiển thị chi tiết 1 đề xuất đang mở xem (định nghĩa đầy đủ, nguồn, bằng chứng, Top-K ứng viên và xử lý đơn)."""
    client = get_client()
    pid = str(proposal.get("id", ""))
    impact = proposal_impact(project, pid)
    stale, stale_reason = is_proposal_candidates_stale(project, proposal, current_model_fingerprint)

    with st.expander(f"🔎 Chi tiết mục đang xem: `{proposal.get('name', '')}` (ID: `{pid}`)", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"**Trạng thái:** {status_label_vn(proposal.get('status', 'pending'))}")
        c2.markdown(f"**Xác thực:** {verification_badge_label(project, proposal, current_model_fingerprint=current_model_fingerprint)}")
        c3.markdown(f"**Tên chuẩn hiện tại:** `{proposal.get('canonical_name') or 'Chưa có'}`")
        c4.markdown(
            f"**Ảnh hưởng:** {len(impact['nodes'])} node · {len(impact['edges'])} cạnh "
            f"({len(impact['direct_edges'])} trực tiếp, {len(impact['indirect_edges'])} gián tiếp)"
        )

        if proposal.get("last_refresh_error"):
            st.error(f"Lỗi làm mới gợi ý gần nhất: {proposal['last_refresh_error']}")
        if stale:
            st.warning(f"⚠️ Gợi ý ứng viên đã cũ: {stale_reason}. Hãy bấm 'Làm mới gợi ý' trước khi dùng để áp dụng hàng loạt.")

        st.markdown(f"**Định nghĩa đầy đủ:** {proposal.get('definition') or '*(Chưa có định nghĩa)*'}")
        if proposal.get("description"):
            st.markdown(f"**Mô tả:** {proposal.get('description')}")

        cands = _render_proposal_observations_and_candidates(project, proposal)
        _render_single_proposal_decision_form(project, client, kind, proposal, pid, cands)
