"""Component Thao tác Hàng loạt, Bản nháp Quyết định, Xem trước (Preview) và Áp dụng Lô cho EDC."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows, compute_project_revision
from frontend.client import FrontendClient, get_client
from frontend.state.session import (
    assign_shared_target_to_drafts,
    fill_top1_candidate_to_drafts,
    get_edc_table_state,
    invalidate_active_preview,
    prepare_batch_decisions_from_scope,
    reconcile_state_after_apply,
    store_active_preview,
    update_proposal_draft,
)
from shared.schemas.edc import (
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
    ProposalDecisionDTO,
)
from shared.text_utils import uid


def build_preview_for_scope(
    project: dict,
    kind: str,
    proposal_ids: list[str],
    *,
    batch_action: str | None = None,
    shared_note: str = "",
    filter_summary: dict[str, Any] | None = None,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> BulkReviewPreviewDTO:
    """Chốt danh sách ID tại thời điểm xem trước, tạo bản nháp và gọi backend preview_proposal_decisions."""
    svc = client or get_client()
    decisions = prepare_batch_decisions_from_scope(
        project,
        kind,
        proposal_ids,
        batch_action=batch_action,
        shared_note=shared_note,
        state_store=state_store,
    )
    req_id = uid()
    req = BulkReviewRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        kind=kind,
        expected_revision=compute_project_revision(project),
        request_id=req_id,
        decisions=decisions,
        apply_mode="all_or_nothing",
        filter_summary=dict(filter_summary or {}),
    )
    preview = svc.preview_proposal_decisions(project, req)
    store_active_preview(project, kind, preview, decisions, request_id=req_id, state_store=state_store)
    return preview


def execute_batch_apply(
    project: dict,
    kind: str,
    *,
    apply_mode: str = "all_or_nothing",
    current_filtered_ids: set[str] | None = None,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> BulkReviewResultDTO:
    """Thực thi commit lô quyết định đã xem trước và cập nhật lại session state."""
    svc = client or get_client()
    t_state = get_edc_table_state(project, kind, state_store)
    active_prev_raw = t_state.get("active_preview")
    if not active_prev_raw:
        raise ValueError("Chưa có bản xem trước hợp lệ. Vui lòng chạy 'Xem trước quyết định' trước khi áp dụng.")

    preview_dto = BulkReviewPreviewDTO.from_dict(active_prev_raw)
    decisions = [ProposalDecisionDTO.from_dict(d) for d in t_state.get("preview_decisions", [])]
    req_id = str(t_state.get("preview_request_id") or uid())

    req = BulkReviewRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        kind=kind,
        expected_revision=preview_dto.revision,
        request_id=req_id,
        decisions=decisions,
        apply_mode=apply_mode,
        filter_summary=dict(t_state.get("filters") or {}),
    )
    result = svc.apply_proposal_decisions(project, req, preview=preview_dto)
    reconcile_state_after_apply(
        project,
        kind,
        result,
        current_filtered_ids=current_filtered_ids,
        state_store=state_store,
    )
    return result


def quick_apply_proposal_batch(
    project: dict,
    kind: str,
    proposal_ids: list[str],
    batch_action: str,
    *,
    shared_note: str = "",
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> BulkReviewResultDTO:
    """Xây dựng bản xem trước và áp dụng ngay lập tức trong 1 thao tác cho đề xuất EDC."""
    preview = build_preview_for_scope(
        project,
        kind,
        proposal_ids,
        batch_action=batch_action,
        shared_note=shared_note,
        client=client,
        state_store=state_store,
    )
    if not preview.can_apply_all and not preview.can_apply_valid_only:
        err_msg = "; ".join(preview.batch_errors) if preview.batch_errors else "Không có mục hợp lệ để áp dụng."
        raise ValueError(err_msg)
    apply_mode = "all_or_nothing" if preview.can_apply_all else "valid_only"
    return execute_batch_apply(project, kind, apply_mode=apply_mode, client=client, state_store=state_store)


def render_edc_bulk_actions(
    project: dict,
    kind: str,
    *,
    selected_ids: list[str],
    eligible_filtered: list[dict],
    filtered_proposals: list[dict],
    current_model_fingerprint: str = "",
) -> None:
    """Hiển thị thanh công cụ thao tác hàng loạt, bảng nháp/xem trước và báo cáo kết quả cho bảng `kind`."""
    client = get_client()
    t_state = get_edc_table_state(project, kind)
    kind_label = "Loại thực thể" if kind == "entity_types" else "Quan hệ"
    selected_count = len(selected_ids)
    filtered_pending_count = len(eligible_filtered)
    filtered_id_set = {str(p.get("id", "")) for p in eligible_filtered}

    # Hiển thị báo cáo kết quả lô gần nhất (giữ qua rerun)
    if t_state.get("last_result"):
        res = BulkReviewResultDTO.from_dict(t_state["last_result"])
        with st.container(border=True):
            st.markdown(f"##### 📋 Báo cáo Kết quả Lô gần nhất (`{res.batch_id}` — {kind_label})")
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Đã áp dụng", res.applied_count)
            r2.metric("Giữ lại để sửa", res.skipped_count)
            r3.metric("Node / Cạnh ảnh hưởng", f"{len(res.affected_node_ids)} / {len(res.affected_edge_ids)}")
            r4.metric("Trạng thái đồng bộ", "Đã đồng bộ" if res.sync_status == "synced" else "Chờ đồng bộ SQLite")

            if res.sync_status == "sync_pending":
                st.warning(
                    f"⚠️ Dữ liệu JSON đã được commit an toàn nhưng SQLite đang chờ đồng bộ ({res.sync_error}). "
                    "Không cần áp dụng lại lô quyết định."
                )
                if st.button("🔄 Đồng bộ lại SQLite ngay", key=f"btn_resync_res_{kind}"):
                    try:
                        client.resync_sqlite(project)
                        res.sync_status = "synced"
                        res.sync_error = ""
                        t_state["last_result"] = res.to_dict()
                        st.success("Đã đồng bộ lại SQLite thành công.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Lỗi đồng bộ lại SQLite: {exc}")

            if st.button("✖️ Đóng báo cáo kết quả lô", key=f"btn_close_res_{kind}"):
                t_state["last_result"] = None
                st.rerun()

    # Hiển thị kết quả làm mới gợi ý gần nhất
    if t_state.get("last_refresh_summary"):
        ref = t_state["last_refresh_summary"]
        with st.container(border=True):
            st.markdown(
                f"**🎯 Kết quả làm mới gợi ý ({kind_label}):** "
                f"Đã làm mới `{ref['refreshed_count']}/{ref['requested_count']}` mục · "
                f"Không có ứng viên vượt ngưỡng: `{ref['empty_candidates_count']}` · "
                f"Lỗi: `{ref['error_count']}`"
            )
            err_rows = [r for r in ref.get("item_results", []) if r.get("status") == "error"]
            if err_rows:
                st.dataframe(err_rows, width='stretch', hide_index=True)
            if st.button("✖️ Đóng thông báo làm mới gợi ý", key=f"btn_close_ref_{kind}"):
                t_state["last_refresh_summary"] = None
                st.rerun()

    st.markdown(f"#### 🛠️ Thao tác Hàng loạt — Bảng {kind_label}")
    target_rows = catalog_rows(project, kind)
    target_names = [r["name"] for r in target_rows]

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button(
            f"🎯 Làm mới gợi ý cho mục đã chọn ({selected_count})",
            disabled=selected_count == 0,
            width='stretch',
            key=f"btn_refresh_sel_{kind}",
        ):
            summary = client.refresh_proposal_candidates(project, selected_ids, kind=kind, save=True)
            t_state["last_refresh_summary"] = summary
            st.rerun()

    with col_b:
        if st.button(
            f"⚡ Điền ứng viên đầu tiên vào bản nháp ({selected_count})",
            disabled=selected_count == 0,
            width='stretch',
            key=f"btn_fill_top1_{kind}",
        ):
            fill_res = fill_top1_candidate_to_drafts(
                project,
                kind,
                selected_ids,
                current_model_fingerprint=current_model_fingerprint,
            )
            t_state["flash_messages"].append(
                f"Đã điền ứng viên Top-1 vào bản nháp cho {fill_res['filled_count']} mục "
                f"(bỏ qua {fill_res['skipped_count']} mục không có ứng viên hợp lệ)."
            )
            st.rerun()

    with col_c:
        if st.button(
            f"📋 Duyệt toàn bộ kết quả lọc ({filtered_pending_count} mục {kind_label})",
            disabled=filtered_pending_count == 0,
            width='stretch',
            key=f"btn_prev_all_filtered_{kind}",
            help=f"Duyệt tất cả {filtered_pending_count} mục đang chờ trong kết quả lọc thành mục mới",
        ):
            all_filtered_ids = [str(p["id"]) for p in eligible_filtered]
            try:
                res = quick_apply_proposal_batch(project, kind, all_filtered_ids, batch_action="approve", client=client)
                t_state["flash_messages"].append(
                    f"Đã duyệt thành công {res.applied_count} mục {kind_label} thành mục mới vào danh mục."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if selected_count > 0:
        with st.container(border=True):
            st.markdown(f"##### ⚡ Thao tác Nhanh cho **{selected_count}** {kind_label} Đang Chọn")
            q1, q2, q3 = st.columns(3)
            with q1:
                if st.button(
                    f"✅ Duyệt ngay {selected_count} mục thành mục mới",
                    type="primary",
                    width='stretch',
                    key=f"btn_quick_app_sel_{kind}",
                    help=f"Duyệt ngay các {kind_label} đã chọn vào danh mục chính thức",
                ):
                    try:
                        res = quick_apply_proposal_batch(project, kind, selected_ids, batch_action="approve", client=client)
                        t_state["flash_messages"].append(
                            f"Đã duyệt thành công {res.applied_count} mục {kind_label} vào danh mục."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            with q2:
                if st.button(
                    f"⚡ Hợp nhất ngay theo Top-1 ({selected_count} mục)",
                    width='stretch',
                    key=f"btn_quick_merge_top1_{kind}",
                    help=f"Tự động điền ứng viên Top-1 và hợp nhất ngay các {kind_label} đã chọn",
                ):
                    try:
                        fill_top1_candidate_to_drafts(
                            project, kind, selected_ids, current_model_fingerprint=current_model_fingerprint
                        )
                        res = quick_apply_proposal_batch(project, kind, selected_ids, batch_action="merge", client=client)
                        t_state["flash_messages"].append(
                            f"Đã hợp nhất thành công {res.applied_count} mục {kind_label} theo ứng viên Top-1."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            with q3:
                if st.button(
                    f"⛔ Từ chối ngay {selected_count} mục đã chọn",
                    width='stretch',
                    key=f"btn_quick_reject_sel_{kind}",
                    help=f"Từ chối các {kind_label} đã chọn",
                ):
                    try:
                        res = quick_apply_proposal_batch(project, kind, selected_ids, batch_action="reject", client=client)
                        t_state["flash_messages"].append(f"Đã từ chối {res.applied_count} mục {kind_label}.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    with st.expander(f"⚙️ Chuẩn bị Bản nháp & Xem trước Quyết định cho {selected_count} mục đã chọn ({kind_label})", expanded=selected_count > 0):
        m1, m2, m3 = st.columns([2.0, 1.2, 1.8])
        shared_target = m1.selectbox(
            f"Chọn cùng một đích có sẵn trong danh mục {kind_label}",
            options=[""] + target_names,
            format_func=lambda x: "— Chọn đích hợp nhất chung —" if not x else x,
            key=f"sel_shared_target_{kind}",
        )
        if m2.button(
            "📌 Gán đích chung vào bản nháp",
            disabled=(selected_count == 0 or not shared_target),
            width='stretch',
            key=f"btn_assign_target_{kind}",
        ):
            cnt = assign_shared_target_to_drafts(project, kind, selected_ids, shared_target)
            t_state["flash_messages"].append(f"Đã gán đích `{shared_target}` vào bản nháp của {cnt} mục đã chọn.")
            st.rerun()

        shared_note = m3.text_input(
            "Ghi chú / Lý do chung cho các mục đã chọn",
            key=f"txt_shared_note_{kind}",
        )

        p1, p2, p3, p4 = st.columns(4)
        if p1.button(
            f"🔍 Xem trước: Duyệt {selected_count} mục đã chọn thành mục mới",
            disabled=selected_count == 0,
            width='stretch',
            key=f"btn_prev_sel_approve_{kind}",
        ):
            build_preview_for_scope(
                project,
                kind,
                selected_ids,
                batch_action="approve",
                shared_note=shared_note,
                filter_summary=dict(t_state.get("filters") or {}),
                client=client,
            )
            st.rerun()

        if p2.button(
            f"🔍 Xem trước: Hợp nhất {selected_count} mục đã chọn",
            disabled=selected_count == 0,
            width='stretch',
            key=f"btn_prev_sel_merge_{kind}",
        ):
            if shared_target:
                assign_shared_target_to_drafts(project, kind, selected_ids, shared_target, note=shared_note)
            build_preview_for_scope(
                project,
                kind,
                selected_ids,
                batch_action="merge",
                shared_note=shared_note,
                filter_summary=dict(t_state.get("filters") or {}),
                client=client,
            )
            st.rerun()

        if p3.button(
            f"🔍 Xem trước: Từ chối {selected_count} mục đã chọn",
            disabled=selected_count == 0,
            width='stretch',
            key=f"btn_prev_sel_reject_{kind}",
        ):
            build_preview_for_scope(
                project,
                kind,
                selected_ids,
                batch_action="reject",
                shared_note=shared_note,
                filter_summary=dict(t_state.get("filters") or {}),
                client=client,
            )
            st.rerun()

        if p4.button(
            f"🔍 Xem trước theo bản nháp hỗn hợp ({selected_count} mục)",
            disabled=selected_count == 0,
            width='stretch',
            key=f"btn_prev_sel_mixed_{kind}",
        ):
            build_preview_for_scope(
                project,
                kind,
                selected_ids,
                batch_action=None,
                shared_note=shared_note,
                filter_summary=dict(t_state.get("filters") or {}),
                client=client,
            )
            st.rerun()

    # Hiển thị Bảng Xem trước (Preview) và Kiểm tra / Áp dụng Lô
    active_prev_raw = t_state.get("active_preview")
    if active_prev_raw:
        preview = BulkReviewPreviewDTO.from_dict(active_prev_raw)
        proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}

        st.markdown(f"#### 🧪 Xem trước Lô Quyết định — Bảng {kind_label} (`{len(preview.locked_proposal_ids)}` mục đã chốt)")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Hợp lệ", preview.valid_count)
        k2.metric("Không hợp lệ (Lỗi)", preview.invalid_count)
        k3.metric("Tổng Node ảnh hưởng (duy nhất)", len(preview.affected_node_ids))
        k4.metric(
            "Tổng Cạnh ảnh hưởng (duy nhất)",
            f"{len(preview.affected_edge_ids)} ({len(preview.direct_edge_ids)} trực tiếp, {len(preview.indirect_edge_ids)} gián tiếp)",
        )

        if preview.batch_errors:
            for b_err in preview.batch_errors:
                st.error(b_err)

        preview_rows = [
            {
                "ID": it["proposal_id"],
                "Tên gốc": it["original_name"],
                "Thao tác": it["action"],
                "Tên chuẩn / Đích": it["canonical_name"],
                "Mô tả": it["description"],
                "Định nghĩa": it["definition"],
                "Ghi chú": it["note"],
                "Hợp lệ": "✅ Hợp lệ" if it["valid"] else f"❌ Lỗi: {'; '.join(it['errors'])}",
                "Cảnh báo": "; ".join(it.get("warnings", [])),
                "Node / Cạnh": (
                    f"{len(it['affected_node_ids'])} node · {len(it['affected_edge_ids'])} cạnh "
                    f"({len(it['indirect_edge_ids'])} gián tiếp)"
                ),
            }
            for it in preview.item_previews
        ]

        edited_preview = st.data_editor(
            preview_rows,
            key=f"preview_editor_{kind}_{preview.preview_id}",
            width='stretch',
            hide_index=True,
            disabled=["ID", "Tên gốc", "Hợp lệ", "Cảnh báo", "Node / Cạnh"],
            column_config={
                "Thao tác": st.column_config.SelectboxColumn(
                    "Thao tác",
                    options=["approve", "merge", "reject"],
                    required=True,
                ),
            },
        )

        # Phát hiện chỉnh sửa trực tiếp trên bảng preview -> cập nhật bản nháp & yêu cầu kiểm tra lại
        draft_modified = False
        for orig_it, edited_row in zip(preview.item_previews, edited_preview):
            if (
                edited_row["Thao tác"] != orig_it["action"]
                or str(edited_row["Tên chuẩn / Đích"] or "").strip() != str(orig_it["canonical_name"] or "").strip()
                or str(edited_row["Mô tả"] or "").strip() != str(orig_it["description"] or "").strip()
                or str(edited_row["Định nghĩa"] or "").strip() != str(orig_it["definition"] or "").strip()
                or str(edited_row["Ghi chú"] or "").strip() != str(orig_it["note"] or "").strip()
            ):
                pid = orig_it["proposal_id"]
                prop = proposals_by_id.get(pid, {"id": pid, "name": orig_it["original_name"]})
                update_proposal_draft(
                    project,
                    kind,
                    prop,
                    action=edited_row["Thao tác"],
                    canonical_name=str(edited_row["Tên chuẩn / Đích"] or ""),
                    description=str(edited_row["Mô tả"] or ""),
                    definition=str(edited_row["Định nghĩa"] or ""),
                    note=str(edited_row["Ghi chú"] or ""),
                )
                draft_modified = True

        if draft_modified:
            st.warning("⚠️ Bạn vừa chỉnh sửa bản nháp quyết định. Kết quả kiểm tra cũ đã hết hiệu lực — hãy bấm 'Kiểm tra lại lô'.")
            if st.button("🔄 Kiểm tra lại lô sau khi chỉnh sửa", type="primary", key=f"btn_repreview_{kind}"):
                build_preview_for_scope(
                    project,
                    kind,
                    preview.locked_proposal_ids,
                    batch_action=None,
                    filter_summary=dict(t_state.get("filters") or {}),
                    client=client,
                )
                st.rerun()
            return

        act_col1, act_col2, act_col3 = st.columns([1.6, 2.0, 1.0])
        with act_col1:
            if st.button(
                f"✅ Áp dụng toàn bộ lô ({preview.valid_count} mục)",
                type="primary",
                disabled=not preview.can_apply_all,
                width='stretch',
                key=f"btn_apply_all_{kind}",
            ):
                try:
                    execute_batch_apply(
                        project,
                        kind,
                        apply_mode="all_or_nothing",
                        current_filtered_ids=filtered_id_set,
                        client=client,
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        with act_col2:
            if preview.can_apply_valid_only:
                confirm_partial = st.checkbox(
                    f"Xác nhận chỉ áp dụng {preview.valid_count} mục hợp lệ, giữ {preview.invalid_count} mục lỗi để sửa tiếp",
                    key=f"chk_partial_{kind}_{preview.preview_id}",
                )
                if st.button(
                    f"⚠️ Áp dụng {preview.valid_count} mục hợp lệ; giữ {preview.invalid_count} mục cần sửa",
                    disabled=not confirm_partial,
                    width='stretch',
                    key=f"btn_apply_partial_{kind}",
                ):
                    try:
                        execute_batch_apply(
                            project,
                            kind,
                            apply_mode="valid_only",
                            current_filtered_ids=filtered_id_set,
                            client=client,
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

        with act_col3:
            if st.button("✖️ Hủy xem trước", width='stretch', key=f"btn_cancel_prev_{kind}"):
                invalidate_active_preview(project, kind)
                st.rerun()

