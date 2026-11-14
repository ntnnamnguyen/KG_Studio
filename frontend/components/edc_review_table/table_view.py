"""Giao diện Bảng Duyệt EDC độc lập cho từng nhóm (`entity_types` / `relations`)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.components.shared_curation_ui import render_selection_action_bar
from frontend.state.session import (
    clear_proposal_selection,
    get_edc_table_state,
    reconcile_selection_with_filter,
    select_all_filtered_proposals,
    select_page_proposals,
    set_focused_proposal,
    sync_keyed_choice,
    sync_keyed_value,
    toggle_proposal_selection,
)
from .drawer import render_proposal_detail_drawer
from .logic import (
    build_table_display_rows,
    compute_filter_signature,
    filter_and_sort_proposals,
    paginate_proposals,
    status_label_vn,
)


def _render_edc_filter_bars(
    project: dict,
    kind: str,
    t_state: dict[str, Any],
    filters: dict[str, Any],
) -> tuple[dict[str, str], int]:
    """Hiển thị 2 tầng bộ lọc cơ bản + nâng cao cho bảng EDC; trả về status_labels và số bộ lọc nâng cao đang bật."""
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    f_tag = (proj_id, kind, int(t_state.get("filter_nonce") or 0))
    docs = project.get("documents", [])
    doc_options = ["all"] + [str(d["id"]) for d in docs]
    doc_labels = {"all": "Tất cả tài liệu", **{str(d["id"]): f"{d.get('name', d['id'])}" for d in docs}}

    adv_edc_count = sum([
        filters.get("doc_id", "all") != "all",
        filters.get("candidate_filter", "all") != "all",
        filters.get("definition_filter", "all") != "all",
        filters.get("origin_filter", "all") != "all",
        filters.get("sort_by", "name") != "name",
    ])
    adv_edc_label = f"⚙️ Bộ lọc & Sắp xếp nâng cao ({adv_edc_count})" if adv_edc_count > 0 else "⚙️ Bộ lọc & Sắp xếp nâng cao"

    # TẦNG 1: THANH CƠ BẢN TINH GỌN (CHỈ 1 DÒNG DUY NHẤT)
    c_edc_search, c_edc_status = st.columns([3.5, 1.5])
    sync_keyed_value(f"flt_search_{kind}", filters.get("search", ""), f_tag)
    filters["search"] = c_edc_search.text_input(
        f"Tìm đề xuất {kind}",
        placeholder="🔍 Tìm nhanh tên đề xuất, tên chuẩn hóa, định nghĩa...",
        label_visibility="collapsed",
        key=f"flt_search_{kind}",
    )
    status_options = ["pending", "all", "approved", "merged", "rejected"]
    status_labels = {
        "pending": "Chờ duyệt (pending)",
        "all": "Tất cả trạng thái",
        "approved": "Đã duyệt mới",
        "merged": "Đã hợp nhất",
        "rejected": "Đã từ chối",
    }
    sync_keyed_choice(f"flt_status_{kind}", status_options, filters.get("status", "pending"), f_tag)
    filters["status"] = c_edc_status.selectbox(
        f"Trạng thái {kind}",
        status_options,
        format_func=lambda s: status_labels.get(s, s),
        label_visibility="collapsed",
        key=f"flt_status_{kind}",
    )

    # TẦNG 2: VÙNG MỞ RỘNG BỘ LỌC NÂNG CAO (Mặc định thu gọn, mở khi có tiêu chí đang lọc)
    with st.expander(adv_edc_label, expanded=bool(adv_edc_count > 0)):
        f3, f4, f5 = st.columns(3)
        sync_keyed_choice(f"flt_doc_{kind}", doc_options, filters.get("doc_id", "all"), f_tag)
        filters["doc_id"] = f3.selectbox(
            "Tài liệu nguồn",
            doc_options,
            format_func=lambda d: doc_labels.get(d, d),
            key=f"flt_doc_{kind}",
        )
        cand_options = ["all", "has_candidates", "no_candidates"]
        cand_labels = {
            "all": "Mọi trạng thái ứng viên",
            "has_candidates": "Đã có ứng viên đích",
            "no_candidates": "Chưa có ứng viên",
        }
        sync_keyed_choice(f"flt_cand_{kind}", cand_options, filters.get("candidate_filter", "all"), f_tag)
        filters["candidate_filter"] = f4.selectbox(
            "Ứng viên",
            cand_options,
            format_func=lambda c: cand_labels[c],
            key=f"flt_cand_{kind}",
        )
        def_options = ["all", "has_definition", "missing_definition"]
        def_labels = {
            "all": "Mọi định nghĩa",
            "has_definition": "Đã có định nghĩa",
            "missing_definition": "Thiếu định nghĩa",
        }
        sync_keyed_choice(f"flt_def_{kind}", def_options, filters.get("definition_filter", "all"), f_tag)
        filters["definition_filter"] = f5.selectbox(
            "Định nghĩa",
            def_options,
            format_func=lambda d: def_labels[d],
            key=f"flt_def_{kind}",
        )

        f6, f7, f8, f_edc_reset = st.columns([1.2, 1.5, 1.0, 0.8])
        origin_options = ["all", "undecided", "auto_aligned", "human_decided"]
        origin_labels = {
            "all": "Mọi nguồn quyết định",
            "undecided": "Chưa có quyết định người dùng",
            "auto_aligned": "Tự động hợp nhất",
            "human_decided": "Con người đã quyết định",
        }
        sync_keyed_choice(f"flt_orig_{kind}", origin_options, filters.get("origin_filter", "all"), f_tag)
        filters["origin_filter"] = f6.selectbox(
            "Nguồn quyết định",
            origin_options,
            format_func=lambda o: origin_labels[o],
            key=f"flt_orig_{kind}",
        )
        sort_options = ["name", "impact_edges", "alignment_score"]
        sort_labels = {
            "name": "Tên đề xuất (A-Z)",
            "impact_edges": "Số cạnh ảnh hưởng (Cao → Thấp)",
            "alignment_score": "Điểm tương đồng (Cao → Thấp)",
        }
        sync_keyed_choice(f"flt_sort_{kind}", sort_options, filters.get("sort_by", "name"), f_tag)
        chosen_sort = f7.selectbox(
            "Sắp xếp theo",
            sort_options,
            format_func=lambda s: sort_labels[s],
            key=f"flt_sort_{kind}",
        )
        filters["sort_by"] = chosen_sort
        filters["sort_desc"] = chosen_sort in ("impact_edges", "alignment_score")
        page_sizes = [20, 50, 100]
        old_psize = int(filters.get("page_size", 50) or 50)
        sync_keyed_choice(f"flt_psize_{kind}", page_sizes, old_psize, f_tag)
        chosen_psize = f8.selectbox(
            "Số dòng / trang",
            page_sizes,
            key=f"flt_psize_{kind}",
        )
        if int(chosen_psize) != old_psize:
            filters["page_size"] = int(chosen_psize)
            filters["page"] = 1
            t_state["page_nonce"] = int(t_state.get("page_nonce") or 0) + 1
            st.rerun()
        f_edc_reset.write("")
        f_edc_reset.write("")
        if f_edc_reset.button("🔄 Đặt lại", key=f"flt_btn_reset_{kind}", help="Xóa toàn bộ bộ lọc"):
            filters["search"] = ""
            filters["status"] = "pending"
            filters["doc_id"] = "all"
            filters["candidate_filter"] = "all"
            filters["definition_filter"] = "all"
            filters["origin_filter"] = "all"
            filters["sort_by"] = "name"
            filters["page"] = 1
            t_state["filter_nonce"] = int(t_state.get("filter_nonce") or 0) + 1
            t_state["page_nonce"] = int(t_state.get("page_nonce") or 0) + 1
            st.rerun()

    return status_labels, adv_edc_count


def render_edc_review_table(
    project: dict,
    kind: str,
    title: str,
    *,
    current_model_fingerprint: str = "",
) -> dict[str, Any]:
    """Hiển thị một bảng độc lập (Loại thực thể hoặc Quan hệ) với bộ lọc, phân trang và chọn theo ID."""
    t_state = get_edc_table_state(project, kind)
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    filters = t_state["filters"]
    all_kind_proposals = [p for p in project.get("schema_proposals", []) if p.get("kind") == kind]
    total_count = len(all_kind_proposals)

    st.markdown(f"### {title}")
    for msg in list(t_state.get("flash_messages", [])):
        st.success(msg)
    t_state["flash_messages"] = []

    status_labels, adv_edc_count = _render_edc_filter_bars(project, kind, t_state, filters)

    filtered_proposals = filter_and_sort_proposals(project, kind, filters)
    filtered_count = len(filtered_proposals)
    eligible_filtered = [p for p in filtered_proposals if p.get("status") == "pending"]

    status_active = status_labels.get(filters.get("status", "pending"), str(filters.get("status", "pending")))
    queue_parts = [f"Trạng thái: **{status_active}**"]
    if str(filters.get("search") or "").strip():
        queue_parts.append(f"Từ khóa: `{filters['search'].strip()}`")
    if adv_edc_count > 0:
        queue_parts.append(f"{adv_edc_count} bộ lọc nâng cao")
    st.caption(
        f"🎯 Bộ lọc đang bật: {' · '.join(queue_parts)} "
        f"({filtered_count}/{total_count} đề xuất khớp). "
        "Phạm vi chọn: **Chọn trang này** chỉ chọn dòng đang xem; **Chọn tất cả lọc** chọn toàn bộ kết quả khớp bộ lọc."
    )

    filter_sig = compute_filter_signature(filters)
    prev_edc_sig = t_state.get("_prev_pagination_sig")
    if prev_edc_sig is None:
        t_state["_prev_pagination_sig"] = filter_sig
    elif prev_edc_sig != filter_sig:
        t_state["_prev_pagination_sig"] = filter_sig
        if int(filters.get("page") or 1) != 1:
            filters["page"] = 1
            t_state["page_nonce"] = int(t_state.get("page_nonce") or 0) + 1
            st.rerun()
    reconcile_selection_with_filter(project, kind, filter_sig, filtered_proposals)
    if t_state.get("filter_prune_notice"):
        st.info(t_state["filter_prune_notice"])

    page_items, cur_page, total_pages = paginate_proposals(
        filtered_proposals,
        page=filters.get("page", 1),
        page_size=filters["page_size"],
    )
    filters["page"] = cur_page

    summary_text = (
        f"**Đã chọn `{len(t_state['selected_ids'])}`** / `{filtered_count}` kết quả lọc "
        f"(`{len(eligible_filtered)}` chờ duyệt) / `{total_count}` tổng số"
    )
    new_p = render_selection_action_bar(
        selected_count=len(t_state["selected_ids"]),
        page_eligible_count=sum(1 for p in page_items if p.get("status") == "pending"),
        filtered_eligible_count=len(eligible_filtered),
        total_count=total_count,
        key_prefix=f"edc_{kind}",
        item_noun="đề xuất",
        on_select_page=lambda: select_page_proposals(project, kind, page_items),
        on_select_all_filtered=lambda: select_all_filtered_proposals(project, kind, filtered_proposals),
        on_clear=lambda: clear_proposal_selection(project, kind),
        current_page=cur_page,
        total_pages=total_pages,
        summary_text=summary_text,
        sync_tag=(proj_id, kind, int(t_state.get("page_nonce") or 0)),
    )
    if isinstance(new_p, int) and new_p != cur_page:
        filters["page"] = new_p
        st.rerun()

    if not filtered_proposals:
        st.info("Không có đề xuất nào khớp bộ lọc hiện tại.")
        return {
            "filtered_proposals": [],
            "eligible_filtered": [],
            "selected_ids": list(t_state["selected_ids"]),
        }

    selected_set = set(t_state["selected_ids"])
    sel_nonce = int(t_state.get("sel_editor_nonce") or 0)
    display_rows = build_table_display_rows(
        project,
        page_items,
        selected_set,
        current_model_fingerprint=current_model_fingerprint,
    )

    edited_rows = st.data_editor(
        display_rows,
        key=f"table_editor_{kind}_{proj_id}_{sel_nonce}_{cur_page}_{filter_sig}",
        width='stretch',
        hide_index=True,
        disabled=[
            "id",
            "Tên đề xuất",
            "Mô tả / Định nghĩa",
            "Ứng viên đích",
            "Điểm tương đồng",
            "Xác thực",
            "Trạng thái",
            "Tên chuẩn",
            "Ảnh hưởng",
            "Nguồn",
        ],
        column_config={
            "id": None,
            "Chọn": st.column_config.CheckboxColumn("Chọn", default=False),
            "Tên đề xuất": st.column_config.TextColumn(
                "Tên Loại thực thể đề xuất (Entity Type)" if kind == "entity_types" else "Tên Quan hệ đề xuất (Relation Type)",
                help="Danh mục phân loại do LLM đề xuất (không phải là thực thể đơn lẻ).",
            ),
        },
    )

    page_changed_selection = False
    for row in edited_rows:
        pid = str(row.get("id", ""))
        want_selected = bool(row.get("Chọn", False))
        was_selected = pid in selected_set
        if want_selected != was_selected:
            toggle_proposal_selection(project, kind, pid, want_selected)
            page_changed_selection = True
    if page_changed_selection:
        st.rerun()

    proposals_by_id = {str(p["id"]): p for p in filtered_proposals}
    detail_ids = [""] + [str(p["id"]) for p in page_items]
    cur_focus = t_state.get("focused_proposal_id", "")
    if cur_focus and cur_focus not in detail_ids and cur_focus in proposals_by_id:
        detail_ids.append(cur_focus)
    if cur_focus not in detail_ids:
        cur_focus = ""

    sync_keyed_choice(
        f"focus_select_{kind}",
        detail_ids,
        cur_focus,
        (proj_id, kind, cur_page, cur_focus, int(t_state.get("focus_nonce") or 0)),
    )
    chosen_focus = st.selectbox(
        "🔍 Mở xem chi tiết 1 dòng (độc lập với các dòng đã tick chọn để thao tác lô)",
        detail_ids,
        format_func=lambda pid: (
            "— Không mở chi tiết —"
            if not pid
            else f"{proposals_by_id[pid]['name']} [{status_label_vn(proposals_by_id[pid].get('status', 'pending'))}] (ID: {pid})"
        ),
        key=f"focus_select_{kind}",
    )
    if chosen_focus != cur_focus:
        set_focused_proposal(project, kind, chosen_focus)
        st.rerun()
    if chosen_focus and chosen_focus in proposals_by_id:
        render_proposal_detail_drawer(
            project,
            kind,
            proposals_by_id[chosen_focus],
            current_model_fingerprint=current_model_fingerprint,
        )

    return {
        "filtered_proposals": filtered_proposals,
        "eligible_filtered": eligible_filtered,
        "selected_ids": list(t_state["selected_ids"]),
    }
