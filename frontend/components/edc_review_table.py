"""Component Bảng Duyệt EDC độc lập cho từng nhóm (`entity_types` / `relations`)."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import (
    batch_proposal_impacts,
    is_proposal_candidates_stale,
    proposal_impact,
)
from frontend.components.shared_curation_ui import paginate_items
from frontend.client import get_client
from frontend.state.session import (
    clear_proposal_selection,
    get_edc_table_state,
    reconcile_selection_with_filter,
    select_all_filtered_proposals,
    select_page_proposals,
    set_focused_proposal,
    toggle_proposal_selection,
)
from shared.catalog_utils import relation_catalog
from shared.text_utils import normal, sha

STATUS_LABELS_VN = {
    "pending": "Chờ duyệt (pending)",
    "approved": "Đã duyệt mới (approved)",
    "merged": "Đã hợp nhất (merged)",
    "rejected": "Đã từ chối (rejected)",
}


def status_label_vn(status: str) -> str:
    return STATUS_LABELS_VN.get(str(status or "pending"), str(status or "pending"))


def verification_badge_label(
    project: dict,
    proposal: dict,
    *,
    current_model_fingerprint: str = "",
) -> str:
    """Phân biệt rõ: gợi ý vector, đã được LLM kiểm tra, tự động hợp nhất, con người quyết định, hoặc gợi ý cũ."""
    origin = str(proposal.get("decision_origin") or "")
    status = str(proposal.get("status") or "pending")
    auto_aligned = bool(proposal.get("auto_aligned", False))
    cands = proposal.get("alignment_candidates") or []

    if status in ("approved", "merged", "rejected") and origin == "human":
        return "Con người quyết định"
    if auto_aligned or origin in ("auto_align", "llm_verified_auto"):
        if origin == "llm_verified_auto" or any(c.get("verified_by_llm") for c in cands):
            return "Tự động hợp nhất (LLM đã kiểm tra)"
        return "Tự động hợp nhất (Vector)"
    if status in ("approved", "merged", "rejected") and not auto_aligned:
        return "Con người quyết định"

    if not cands:
        if proposal.get("last_refresh_error"):
            return "Lỗi làm mới gợi ý"
        return "Chưa có gợi ý"

    stale, _ = is_proposal_candidates_stale(project, proposal, current_model_fingerprint)
    suffix = " [Gợi ý cũ]" if stale else ""
    if any(c.get("verified_by_llm") for c in cands):
        return f"Đã được LLM kiểm tra{suffix}"
    return f"Gợi ý vector{suffix}"


def compute_filter_signature(filters: dict[str, Any]) -> str:
    """Chữ ký xác định cho bộ lọc (không tính page và sort_by để đổi trang/sắp xếp vẫn giữ nguyên lựa chọn)."""
    relevant = {
        "status": str(filters.get("status", "pending")),
        "search": normal(str(filters.get("search", ""))),
        "doc_id": str(filters.get("doc_id", "all")),
        "candidate_filter": str(filters.get("candidate_filter", "all")),
        "definition_filter": str(filters.get("definition_filter", "all")),
        "origin_filter": str(filters.get("origin_filter", "all")),
    }
    return sha(json.dumps(relevant, ensure_ascii=False, sort_keys=True))[:16]


def filter_and_sort_proposals(
    project: dict,
    kind: str,
    filters: dict[str, Any],
) -> list[dict]:
    """Lọc và sắp xếp đề xuất của đúng nhóm `kind`."""
    all_for_kind = [p for p in project.get("schema_proposals", []) if p.get("kind") == kind]
    status_f = str(filters.get("status", "pending") or "pending")
    search_q = normal(str(filters.get("search", "")))
    doc_f = str(filters.get("doc_id", "all") or "all")
    cand_f = str(filters.get("candidate_filter", "all") or "all")
    def_f = str(filters.get("definition_filter", "all") or "all")
    origin_f = str(filters.get("origin_filter", "all") or "all")
    sort_by = str(filters.get("sort_by", "name") or "name")
    sort_desc = bool(filters.get("sort_desc", False))

    filtered: list[dict] = []
    for prop in all_for_kind:
        p_status = str(prop.get("status", "pending"))
        if status_f != "all" and p_status != status_f:
            continue

        if search_q:
            haystack = " ".join(
                [
                    normal(str(prop.get("name", ""))),
                    normal(str(prop.get("canonical_name", ""))),
                    normal(str(prop.get("definition", ""))),
                    normal(str(prop.get("description", ""))),
                ]
            )
            if search_q not in haystack:
                continue

        if doc_f != "all":
            obs_docs = {str(o.get("doc_id", "")) for o in prop.get("observations", []) if o.get("doc_id")}
            if doc_f not in obs_docs:
                continue

        cands = prop.get("alignment_candidates") or []
        if cand_f == "has_candidates" and not cands:
            continue
        if cand_f == "no_candidates" and cands:
            continue

        has_def = bool(str(prop.get("definition", "")).strip())
        if def_f == "missing_definition" and has_def:
            continue
        if def_f == "has_definition" and not has_def:
            continue

        is_auto = bool(prop.get("auto_aligned", False)) or prop.get("decision_origin") in (
            "auto_align",
            "llm_verified_auto",
        )
        is_human = p_status in ("approved", "merged", "rejected") and not is_auto
        if origin_f == "auto_aligned" and not is_auto:
            continue
        if origin_f == "human_decided" and not is_human:
            continue
        if origin_f == "undecided" and is_human:
            continue

        filtered.append(prop)

    # Chỉ tính reverse impact khi người dùng sắp xếp theo số lượng cạnh bị ảnh hưởng
    impact_cache = batch_proposal_impacts(project, [p["id"] for p in filtered]) if (sort_by == "impact_edges") else {}

    def _sort_key(p: dict) -> Any:
        if sort_by == "impact_edges":
            return (len(impact_cache[p["id"]]["edges"]), len(impact_cache[p["id"]]["nodes"]), normal(p.get("name", "")))
        if sort_by == "alignment_score":
            cands = p.get("alignment_candidates") or []
            top_score = float(cands[0].get("score", 0.0)) if cands else float(p.get("alignment_score", 0.0) or 0.0)
            return (top_score, normal(p.get("name", "")))
        return normal(p.get("name", ""))

    return sorted(filtered, key=_sort_key, reverse=sort_desc)


def paginate_proposals(
    proposals: list[dict],
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int, int]:
    """Phân trang danh sách đề xuất; sử dụng hàm paginate_items dùng chung."""
    return paginate_items(proposals, page=page, page_size=page_size)


def build_table_display_rows(
    project: dict,
    proposals: list[dict],
    selected_ids: set[str],
    *,
    current_model_fingerprint: str = "",
) -> list[dict[str, Any]]:
    """Tạo dữ liệu bảng hiển thị chuẩn 10 cột theo đặc tả mục 2.1."""
    rows: list[dict[str, Any]] = []
    for prop in proposals:
        pid = str(prop.get("id", ""))
        impact = proposal_impact(project, pid)
        cands = prop.get("alignment_candidates") or []
        top_cand_name = str(cands[0].get("name", "")) if cands else "Chưa có"
        top_score = float(cands[0].get("score", 0.0)) if cands else float(prop.get("alignment_score", 0.0) or 0.0)
        score_text = f"{top_score:.2f}" if (cands or top_score > 0.0) else "—"

        raw_def = str(prop.get("definition") or prop.get("description") or "").strip()
        short_def = (raw_def[:90] + "…") if len(raw_def) > 90 else (raw_def or "(Thiếu định nghĩa)")

        obs = prop.get("observations") or []
        doc_ids = {str(o.get("doc_id", "")) for o in obs if o.get("doc_id")}
        indirect_cnt = len(impact.get("indirect_edges", []))
        impact_label = f"{len(impact['nodes'])} node · {len(impact['edges'])} cạnh"
        if indirect_cnt > 0:
            impact_label += f" ({indirect_cnt} gián tiếp)"

        rows.append(
            {
                "id": pid,
                "Chọn": pid in selected_ids,
                "Tên đề xuất": str(prop.get("name", "")),
                "Mô tả / Định nghĩa": short_def,
                "Ứng viên đích": top_cand_name,
                "Điểm tương đồng": score_text,
                "Xác thực": verification_badge_label(
                    project,
                    prop,
                    current_model_fingerprint=current_model_fingerprint,
                ),
                "Trạng thái": status_label_vn(str(prop.get("status", "pending"))),
                "Tên chuẩn": str(prop.get("canonical_name", "")) or "—",
                "Ảnh hưởng": impact_label,
                "Nguồn": f"{len(doc_ids) or (1 if obs else 0)} tài liệu / {len(obs)} quan sát",
            }
        )
    return rows


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


def render_edc_review_table(
    project: dict,
    kind: str,
    title: str,
    *,
    current_model_fingerprint: str = "",
) -> dict[str, Any]:
    """Hiển thị một bảng độc lập (Loại thực thể hoặc Quan hệ) với bộ lọc, phân trang và chọn theo ID."""
    t_state = get_edc_table_state(project, kind)
    filters = t_state["filters"]
    all_kind_proposals = [p for p in project.get("schema_proposals", []) if p.get("kind") == kind]
    total_count = len(all_kind_proposals)

    st.markdown(f"### {title}")
    for msg in list(t_state.get("flash_messages", [])):
        st.success(msg)
    t_state["flash_messages"] = []

    docs = project.get("documents", [])
    doc_options = ["all"] + [str(d["id"]) for d in docs]
    doc_labels = {"all": "Tất cả tài liệu", **{str(d["id"]): f"{d.get('name', d['id'])}" for d in docs}}

    f1, f2, f3, f4 = st.columns([1.2, 1.8, 1.3, 1.2])
    status_options = ["pending", "all", "approved", "merged", "rejected"]
    status_labels = {
        "pending": "Chờ duyệt (pending)",
        "all": "Tất cả trạng thái",
        "approved": "Đã duyệt mới",
        "merged": "Đã hợp nhất",
        "rejected": "Đã từ chối",
    }
    filters["status"] = f1.selectbox(
        "Trạng thái",
        status_options,
        index=status_options.index(filters.get("status", "pending")) if filters.get("status", "pending") in status_options else 0,
        format_func=lambda s: status_labels.get(s, s),
        key=f"flt_status_{kind}",
    )
    filters["search"] = f2.text_input(
        "Tìm tên đề xuất / tên chuẩn / định nghĩa",
        value=filters.get("search", ""),
        key=f"flt_search_{kind}",
    )
    filters["doc_id"] = f3.selectbox(
        "Tài liệu nguồn",
        doc_options,
        index=doc_options.index(filters.get("doc_id", "all")) if filters.get("doc_id", "all") in doc_options else 0,
        format_func=lambda d: doc_labels.get(d, d),
        key=f"flt_doc_{kind}",
    )
    cand_options = ["all", "has_candidates", "no_candidates"]
    cand_labels = {
        "all": "Mọi trạng thái ứng viên",
        "has_candidates": "Đã có ứng viên đích",
        "no_candidates": "Chưa có ứng viên",
    }
    filters["candidate_filter"] = f4.selectbox(
        "Ứng viên",
        cand_options,
        index=cand_options.index(filters.get("candidate_filter", "all")),
        format_func=lambda c: cand_labels[c],
        key=f"flt_cand_{kind}",
    )

    f5, f6, f7, f8 = st.columns([1.2, 1.3, 1.3, 1.0])
    def_options = ["all", "has_definition", "missing_definition"]
    def_labels = {
        "all": "Mọi định nghĩa",
        "has_definition": "Đã có định nghĩa",
        "missing_definition": "Thiếu định nghĩa",
    }
    filters["definition_filter"] = f5.selectbox(
        "Định nghĩa",
        def_options,
        index=def_options.index(filters.get("definition_filter", "all")),
        format_func=lambda d: def_labels[d],
        key=f"flt_def_{kind}",
    )
    origin_options = ["all", "undecided", "auto_aligned", "human_decided"]
    origin_labels = {
        "all": "Mọi nguồn quyết định",
        "undecided": "Chưa có quyết định người dùng",
        "auto_aligned": "Tự động hợp nhất",
        "human_decided": "Con người đã quyết định",
    }
    filters["origin_filter"] = f6.selectbox(
        "Nguồn quyết định",
        origin_options,
        index=origin_options.index(filters.get("origin_filter", "all")),
        format_func=lambda o: origin_labels[o],
        key=f"flt_orig_{kind}",
    )
    sort_options = ["name", "impact_edges", "alignment_score"]
    sort_labels = {
        "name": "Tên đề xuất (A-Z)",
        "impact_edges": "Số cạnh ảnh hưởng (Cao → Thấp)",
        "alignment_score": "Điểm tương đồng (Cao → Thấp)",
    }
    chosen_sort = f7.selectbox(
        "Sắp xếp theo",
        sort_options,
        index=sort_options.index(filters.get("sort_by", "name")),
        format_func=lambda s: sort_labels[s],
        key=f"flt_sort_{kind}",
    )
    filters["sort_by"] = chosen_sort
    filters["sort_desc"] = chosen_sort in ("impact_edges", "alignment_score")
    page_sizes = [20, 50, 100]
    filters["page_size"] = f8.selectbox(
        "Số dòng / trang",
        page_sizes,
        index=page_sizes.index(filters.get("page_size", 50)) if filters.get("page_size", 50) in page_sizes else 1,
        key=f"flt_psize_{kind}",
    )

    filtered_proposals = filter_and_sort_proposals(project, kind, filters)
    filtered_count = len(filtered_proposals)
    eligible_filtered = [p for p in filtered_proposals if p.get("status") == "pending"]

    filter_sig = compute_filter_signature(filters)
    reconcile_selection_with_filter(project, kind, filter_sig, filtered_proposals)
    if t_state.get("filter_prune_notice"):
        st.info(t_state["filter_prune_notice"])

    page_items, cur_page, total_pages = paginate_proposals(
        filtered_proposals,
        page=filters.get("page", 1),
        page_size=filters["page_size"],
    )
    filters["page"] = cur_page

    b1, b2, b3, b4, b5 = st.columns([1.2, 1.5, 1.0, 1.2, 2.2])
    if b1.button(
        f"☑️ Chọn trang này ({sum(1 for p in page_items if p.get('status') == 'pending')})",
        disabled=not any(p.get("status") == "pending" for p in page_items),
        key=f"btn_sel_page_{kind}",
        width='stretch',
    ):
        select_page_proposals(project, kind, page_items)
        st.rerun()

    if b2.button(
        f"☑️ Chọn tất cả kết quả lọc ({len(eligible_filtered)})",
        disabled=len(eligible_filtered) == 0,
        key=f"btn_sel_all_{kind}",
        width='stretch',
    ):
        select_all_filtered_proposals(project, kind, filtered_proposals)
        st.rerun()

    if b3.button(
        "⬜ Bỏ chọn",
        disabled=len(t_state["selected_ids"]) == 0,
        key=f"btn_clear_sel_{kind}",
        width='stretch',
    ):
        clear_proposal_selection(project, kind)
        st.rerun()

    if total_pages > 1:
        filters["page"] = b4.number_input(
            f"Trang (1..{total_pages})",
            min_value=1,
            max_value=total_pages,
            value=cur_page,
            step=1,
            key=f"num_page_{kind}",
        )

    b5.markdown(
        f"**Đã chọn `{len(t_state['selected_ids'])}`** / `{filtered_count}` kết quả lọc "
        f"(`{len(eligible_filtered)}` chờ duyệt) / `{total_count}` tổng số"
    )

    if not filtered_proposals:
        st.info("Không có đề xuất nào khớp bộ lọc hiện tại.")
        return {
            "filtered_proposals": [],
            "eligible_filtered": [],
            "selected_ids": list(t_state["selected_ids"]),
        }

    selected_set = set(t_state["selected_ids"])
    display_rows = build_table_display_rows(
        project,
        page_items,
        selected_set,
        current_model_fingerprint=current_model_fingerprint,
    )

    edited_rows = st.data_editor(
        display_rows,
        key=f"table_editor_{kind}_{cur_page}_{filter_sig}",
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

    chosen_focus = st.selectbox(
        "🔍 Mở xem chi tiết 1 dòng (độc lập với các dòng đã tick chọn để thao tác lô)",
        detail_ids,
        index=detail_ids.index(cur_focus) if cur_focus in detail_ids else 0,
        format_func=lambda pid: (
            "— Không mở chi tiết —"
            if not pid
            else f"{proposals_by_id[pid]['name']} [{status_label_vn(proposals_by_id[pid].get('status', 'pending'))}] (ID: {pid})"
        ),
        key=f"focus_select_{kind}",
    )
    if chosen_focus != cur_focus:
        set_focused_proposal(project, kind, chosen_focus)
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

