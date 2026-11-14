"""Tab 2: Phát hiện quan hệ nghi trùng, Gộp quan hệ hàng loạt & Bàn gộp quan hệ thủ công."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from backend.domain.catalogs.service import compute_project_revision
from backend.domain.curation.service import compute_apparent_duplicate_edge_groups
from backend.integrations.llm.providers import DEFAULT_MODELS
from frontend.client import FrontendClient
from frontend.components.merge.provenance_view import render_relation_provenance_panel
from frontend.state.session import (
    bump_sync_nonce,
    reset_curation_state_if_project_changed,
    reset_edc_state_if_project_changed,
    sync_keyed_choice,
    sync_keyed_multiselect,
    sync_keyed_value,
)


def _render_ai_semantic_relation_section(project: dict, client: FrontendClient) -> None:
    """Phần 1: Quét & gom cụm quan hệ ngữ nghĩa bằng LLM."""
    with st.container(border=True):
        st.markdown("#### 🤖 1. Quét & Gom cụm Quan hệ Ngữ nghĩa bằng AI (DeepSeek Semantic Clustering)")
        st.caption(
            "Sử dụng LLM (DeepSeek) để phân tích sâu sắc ngữ nghĩa tiếng Việt của toàn bộ các quan hệ trên đồ thị, "
            "tự động phát hiện các nhóm từ đồng nghĩa / biến thể diễn đạt (ví dụ: 'tọa lạc tại', 'nằm ở', 'thuộc địa phận' -> gom về 'nằm tại'). "
            "Giải quyết triệt để lỗi phân mảnh schema mà thuật toán so khớp ký tự bề mặt không phát hiện được."
        )

        llm_prov = st.session_state.get("llm_provider", "DeepSeek")
        llm_mod = st.session_state.get("llm_model") or DEFAULT_MODELS.get(llm_prov, "deepseek-chat")
        llm_k = st.session_state.get("llm_api_key", "")
        key_label = "✅ Đã nạp API Key" if llm_k else "⚠️ Chưa có API Key (Vui lòng thiết lập tại Bước 2 hoặc thanh bên)"
        st.caption(f"🤖 Đang sử dụng kết nối LLM hệ thống: **{llm_prov}** (`{llm_mod}`) · {key_label}")

        proj_id = str(project.get("project_id") or project.get("name") or "default")
        scope_col1, _ = st.columns([3.0, 3.0])
        scope_choices = {
            "top_50": "Top 50 quan hệ phổ biến nhất (Khuyến nghị - Nhanh, chuẩn xác)",
            "top_100": "Top 100 quan hệ phổ biến nhất",
            "freq_ge_2": "Quan hệ có từ 2 cạnh trở lên (freq >= 2)",
            "all": "Toàn bộ quan hệ hiện có trên đồ thị (Tất cả)",
        }
        sel_rel_scope_key = f"ai_rel_scope_{proj_id}"
        curr_rel_scope = st.session_state.get(sel_rel_scope_key, "top_50")
        if curr_rel_scope not in scope_choices:
            curr_rel_scope = "top_50"
        scope_widget_key = f"sb_{sel_rel_scope_key}"
        sync_keyed_choice(
            scope_widget_key,
            list(scope_choices.keys()),
            curr_rel_scope,
            (proj_id, "rel_scope"),
        )
        chosen_rel_scope = scope_col1.selectbox(
            "Phạm vi quan hệ gửi tới AI (Scan Scope)",
            options=list(scope_choices.keys()),
            format_func=lambda k: scope_choices[k],
            key=scope_widget_key,
            help="Giới hạn phạm vi giúp prompt ngắn gọn (~500 - 2,500 tokens), tránh vượt quá giới hạn ngữ cảnh của DeepSeek và tăng tốc độ xử lý.",
        )
        st.session_state[sel_rel_scope_key] = chosen_rel_scope

        with st.expander("📝 Tùy chỉnh Prompt & Chỉ dẫn Gom cụm Quan hệ theo ý muốn (Custom Instructions)", expanded=False):
            st.caption(
                "Bạn có thể bổ sung các quy tắc gom nhóm cụ thể cho quan hệ (ví dụ: chỉ gộp các quan hệ về vị trí địa lý, "
                "bỏ qua quan hệ thời gian, hoặc yêu cầu ưu tiên tên chuẩn theo chuẩn mực riêng của bạn)."
            )
            inst_widget_key = f"ta_ai_rel_custom_inst_{proj_id}"
            sync_keyed_value(
                inst_widget_key,
                str(st.session_state.get(f"ai_rel_custom_inst_{proj_id}", "")),
                (proj_id, "init"),
            )
            rel_custom_inst = st.text_area(
                "Chỉ dẫn / Quy tắc gom cụm bổ sung cho AI (Prompt Instructions)",
                placeholder="Ví dụ: Chỉ gom nhóm các quan hệ chỉ vị trí địa lý; Bỏ qua quan hệ năm tháng; Ưu tiên đặt tên chuẩn theo dạng 'ở_tại'...",
                key=inst_widget_key,
                help="Các chỉ dẫn này sẽ được tiêm trực tiếp vào prompt gửi cho DeepSeek/LLM với độ ưu tiên cao nhất.",
            )
            st.session_state[f"ai_rel_custom_inst_{proj_id}"] = rel_custom_inst

            col_p_btn, _ = st.columns([2.5, 3.5])
            show_prompt_widget_key = f"cb_ai_rel_show_prompt_{proj_id}"
            sync_keyed_value(
                show_prompt_widget_key,
                bool(st.session_state.get(f"ai_rel_show_prompt_{proj_id}", False)),
                (proj_id, "init"),
            )
            show_prompt_preview = col_p_btn.checkbox(
                "👁️ Xem trước toàn bộ Prompt gửi LLM",
                key=show_prompt_widget_key,
            )
            st.session_state[f"ai_rel_show_prompt_{proj_id}"] = show_prompt_preview

            if show_prompt_preview:
                preview_p = client.preview_clustering_prompt(
                    project, kind="relations", custom_instructions=rel_custom_inst, scope=chosen_rel_scope
                )
                st.caption(f"Độ dài Prompt: **{len(preview_p):,}** ký tự (~{len(preview_p)//3.5:.0f} tokens)")
                st.markdown("**Bản xem trước Prompt hoàn chỉnh:**")
                st.code(preview_p, language="markdown")

        btn_scan_col, _ = st.columns([2.2, 3.8])
        if btn_scan_col.button(
            "🤖 Bắt đầu Quét & Gom cụm Quan hệ bằng AI",
            key=f"btn_scan_rel_ai_{project.get('project_id', 'curr')}",
            type="primary",
        ):
            if not llm_k and llm_prov != "Ollama (Local)":
                st.error(f"❌ Chưa có API Key cho `{llm_prov}`. Vui lòng thiết lập API Key tại thanh bên (Sidebar) hoặc Bước 2.")
            else:
                with st.spinner(f"Đang gửi yêu cầu tới {llm_prov} API để phân tích ngữ nghĩa và gom cụm quan hệ..."):
                    try:
                        custom_i = st.session_state.get(f"ai_rel_custom_inst_{project.get('project_id', 'curr')}", "")
                        scan_res = client.scan_semantic_clusters(
                            project,
                            kind="relations",
                            scope=chosen_rel_scope,
                            provider=llm_prov,
                            api_key=llm_k,
                            model=llm_mod,
                            custom_instructions=custom_i,
                        )
                        st.session_state[f"ai_rel_clusters_{project.get('project_id', 'curr')}"] = scan_res
                        if scan_res.get("clusters_count", 0) > 0:
                            st.success(f"Đã phát hiện {scan_res['clusters_count']} cụm quan hệ tương đương từ {scan_res['scanned_items_count']} quan hệ!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Lỗi khi quét gom cụm: {exc}")

        ai_res = st.session_state.get(f"ai_rel_clusters_{project.get('project_id', 'curr')}")
        if ai_res:
            if ai_res.get("clusters"):
                st.markdown("---")
                st.markdown(f"##### 🎯 Đề xuất Gom cụm ({len(ai_res['clusters'])} cụm được tìm thấy từ {ai_res.get('scanned_items_count', 0)} quan hệ)")

                if ai_res.get("used_prompt"):
                    with st.expander("📄 Xem lại Prompt đã gửi cho lượt quét này", expanded=False):
                        st.code(ai_res["used_prompt"], language="markdown")

                selected_clusters_to_apply = []
                for c in ai_res["clusters"]:
                    cid = c["id"]
                    c_box = st.container(border=True)
                    col_chk, col_info = c_box.columns([0.8, 5.2])
                    chk_key = f"chk_ai_rel_{proj_id}_{cid}"
                    sync_keyed_value(chk_key, True, (proj_id, str(cid)))
                    is_checked = col_chk.checkbox("Chọn", key=chk_key)
                    with col_info:
                        st.markdown(f"**Tên chuẩn hóa:** `{c['canonical_name']}` &nbsp;|&nbsp; **Số cạnh ảnh hưởng:** `{c['affected_count']}` cạnh")
                        syns_str = ", ".join(f"`{s}`" for s in c["synonyms"])
                        st.markdown(f"**Các biến thể sẽ gộp về tên chuẩn:** {syns_str}")
                        st.caption(f"💡 *Lý do ngữ nghĩa:* {c['reason']}")
                    if is_checked:
                        selected_clusters_to_apply.append(c)

                c_act1, c_act2 = st.columns([3.0, 3.0])
                ai_collapse_key = f"cb_ai_rel_collapse_{proj_id}"
                sync_keyed_value(ai_collapse_key, True, (proj_id, "ai_collapse"))
                cb_collapse = c_act1.checkbox(
                    "☑️ Tự động khử trùng các bộ ba lặp nhau phát sinh sau gộp (Triple Deduplication)",
                    key=ai_collapse_key,
                )
                if c_act2.button(
                    f"🚀 Áp dụng Gom cụm cho {len(selected_clusters_to_apply)} cụm đã chọn",
                    disabled=len(selected_clusters_to_apply) == 0,
                    type="primary",
                    key=f"btn_apply_ai_rel_{proj_id}",
                ):
                    try:
                        res_apply = client.apply_semantic_clusters(
                            project,
                            kind="relations",
                            approved_clusters=selected_clusters_to_apply,
                            collapse_duplicate_edges=cb_collapse,
                            note="Gom cụm quan hệ tự động bằng DeepSeek AI",
                        )
                        st.session_state.pop(f"ai_rel_clusters_{proj_id}", None)
                        st.session_state.pop(f"selected_rel_pairs_{proj_id}", None)
                        bump_sync_nonce(f"_rel_merge_nonce_{proj_id}")
                        reset_edc_state_if_project_changed(project, force=True)
                        reset_curation_state_if_project_changed(project, force=True)
                        dup_msg = f" và khử {res_apply.merged_duplicate_edges} cạnh trùng." if res_apply.merged_duplicate_edges > 0 else "."
                        st.success(f"Đã gộp thành công {res_apply.applied_count} biến thể quan hệ, đổi {len(res_apply.affected_edge_ids)} cạnh{dup_msg}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Lỗi khi áp dụng gộp: {exc}")
            else:
                st.markdown("---")
                st.warning(
                    f"ℹ️ Đã quét xong **{ai_res.get('scanned_items_count', 0)}** quan hệ trong phạm vi đã chọn, "
                    "nhưng AI không phát hiện nhóm từ đồng nghĩa nào cần gom cụm, hoặc các đề xuất trả về không khớp với danh sách quan hệ."
                )
                if ai_res.get("raw_response"):
                    with st.expander("🔍 Xem phản hồi gốc từ DeepSeek API (Raw Response)", expanded=False):
                        st.code(ai_res["raw_response"], language="json")
                if ai_res.get("used_prompt"):
                    with st.expander("📄 Xem lại Prompt đã gửi", expanded=False):
                        st.code(ai_res["used_prompt"], language="markdown")


def _render_fuzzy_relation_matching_section(
    project: dict,
    client: FrontendClient,
    m_state: dict[str, Any],
) -> None:
    """Phần 2: Phát hiện & gộp quan hệ nghi trùng theo ký tự (Fuzzy Matching)."""
    with st.container(border=True):
        st.markdown("#### 🔍 2. Phát hiện & Gộp Quan hệ Tương đồng theo Ký tự (Fuzzy Matching)")
        st.caption(
            "Tự động rà soát toàn bộ các cạnh trong đồ thị để phát hiện các cặp quan hệ có tên gần giống nhau "
            "(biến thể gạch dưới / dấu cách, dạng viết thường / hoa, tiền tố/hậu tố, tương đồng ký tự Levenshtein hoặc giao thoa từ khóa). "
            "Gộp quan hệ giúp chuẩn hóa ontology, đồng nhất các cạnh và giải quyết triệt để lỗi phân mảnh schema."
        )

        proj_id = str(project.get("project_id") or project.get("name") or "default")
        rc1, rc2 = st.columns([1.6, 2.4])
        sync_keyed_value(
            "merge_rel_fuzzy_slider",
            float(m_state.get("rel_fuzzy_threshold", 0.75)),
            (proj_id, "rel_fuzzy"),
        )
        fuzzy_rel_val = rc1.slider(
            "Ngưỡng tương đồng quan hệ (Fuzzy threshold)",
            min_value=0.50,
            max_value=0.98,
            step=0.02,
            key="merge_rel_fuzzy_slider",
        )
        m_state["rel_fuzzy_threshold"] = fuzzy_rel_val
        rel_suggestions = client.relation_duplicate_suggestions(project, fuzzy_threshold=fuzzy_rel_val)
        rc2.caption(
            f"Tìm thấy **{len(rel_suggestions)}** cặp quan hệ nghi trùng · "
            f"Đã đánh dấu **{len(project.get('not_duplicate_relation_pairs', []))}** cặp khác quan hệ."
        )

        sel_rel_pairs_key = f"selected_rel_pairs_{project.get('project_id', 'curr')}"
        if sel_rel_pairs_key not in st.session_state:
            st.session_state[sel_rel_pairs_key] = set()

        valid_rel_keys = {f"{s['relation_a']}___{s['relation_b']}" for s in rel_suggestions}
        st.session_state[sel_rel_pairs_key] = {
            k for k in st.session_state[sel_rel_pairs_key]
            if k in valid_rel_keys
        }

        if rel_suggestions:
            rb1, rb2, _ = st.columns([1.5, 1.5, 3.0])
            if rb1.button("☑️ Chọn tất cả", key="btn_sel_all_rel_pairs", width='stretch'):
                st.session_state[sel_rel_pairs_key] = {
                    f"{s['relation_a']}___{s['relation_b']}" for s in rel_suggestions
                }
                st.rerun()

            if rb2.button("✖️ Bỏ chọn", key="btn_clear_rel_pairs", width='stretch'):
                st.session_state[sel_rel_pairs_key] = set()
                st.rerun()

            cur_rel_sel = st.session_state.get(sel_rel_pairs_key, set())
            table_rel_rows = [
                {
                    "pair_key": f"{s['relation_a']}___{s['relation_b']}",
                    "rel_a": s["relation_a"],
                    "rel_b": s["relation_b"],
                    "drop_rel": s.get("suggested_drop") or s.get("source") or s["relation_b"],
                    "target_rel": s.get("suggested_target") or s.get("target") or s["relation_a"],
                    "Chọn": f"{s['relation_a']}___{s['relation_b']}" in cur_rel_sel,
                    "Cặp": f"#{idx}",
                    "Quan hệ A (Số cạnh)": f"{s['relation_a']} ({s['count_a']})",
                    "Quan hệ B (Số cạnh)": f"{s['relation_b']} ({s['count_b']})",
                    "Đề xuất chuẩn hóa thành": s.get("suggested_target") or s.get("target") or s["relation_a"],
                    "Lý do nghi trùng": s["reason"],
                    "Điểm tương đồng": s["score"],
                }
                for idx, s in enumerate(rel_suggestions, 1)
            ]
            proj_rev = compute_project_revision(project)
            edited_rels = st.data_editor(
                table_rel_rows,
                key=f"editor_rel_pairs_{proj_rev}_{fuzzy_rel_val}",
                width='stretch',
                hide_index=True,
                disabled=[
                    "pair_key",
                    "rel_a",
                    "rel_b",
                    "drop_rel",
                    "target_rel",
                    "Cặp",
                    "Quan hệ A (Số cạnh)",
                    "Quan hệ B (Số cạnh)",
                    "Đề xuất chuẩn hóa thành",
                    "Lý do nghi trùng",
                    "Điểm tương đồng",
                ],
                column_config={
                    "pair_key": None,
                    "id_a": None,
                    "id_b": None,
                    "drop_rel": None,
                    "target_rel": None,
                    "Chọn": st.column_config.CheckboxColumn("Chọn", default=False),
                },
            )

            new_rel_sel = {r["pair_key"] for r in edited_rels if r.get("Chọn")}
            if new_rel_sel != cur_rel_sel:
                st.session_state[sel_rel_pairs_key] = new_rel_sel
                st.rerun()

            selected_rel_items = [
                s for s in rel_suggestions
                if f"{s['relation_a']}___{s['relation_b']}" in st.session_state.get(sel_rel_pairs_key, set())
            ]

            if selected_rel_items:
                with st.container(border=True):
                    st.markdown(f"##### ⚡ Thao tác Nhanh cho **{len(selected_rel_items)}** Cặp Quan hệ Đang Chọn")

                    with st.expander("🔍 Đối chiếu Ngữ cảnh Văn bản của các Quan hệ Đang Chọn", expanded=False):
                        sel_rel_names = list(dict.fromkeys(
                            [s["relation_a"] for s in selected_rel_items] + [s["relation_b"] for s in selected_rel_items]
                        ))
                        render_relation_provenance_panel(project, sel_rel_names)

                    sync_keyed_value("cb_bulk_rel_collapse", False, (proj_id, "bulk_rel_collapse"))
                    cb_bulk_collapse = st.checkbox(
                        "Tự động hợp nhất các cạnh trùng bộ ba (dồn bằng chứng đầy đủ)",
                        key="cb_bulk_rel_collapse",
                        help="Nếu việc gộp quan hệ dẫn tới các cạnh có cùng nguồn, quan hệ và đích, hệ thống sẽ tự động gộp thành 1 cạnh duy nhất và dồn toàn bộ trích dẫn nguyên văn lại.",
                    )
                    ract_col1, ract_col2 = st.columns([1.5, 1.5])
                    if ract_col1.button(
                        f"⚡ Gộp nhanh {len(selected_rel_items)} quan hệ đã chọn (Bulk Relation Merge)",
                        type="primary",
                        width='stretch',
                        key="btn_bulk_merge_relations",
                        help="Tự động chuẩn hóa các biến thể quan hệ về quan hệ đích đề xuất, cập nhật toàn bộ cạnh, bảng relation_redirects, lưu aliases và danh mục.",
                    ):
                        try:
                            mapping = {
                                (s.get("suggested_drop") or s.get("source") or s["relation_b"]): (
                                    s.get("suggested_target") or s.get("target") or s["relation_a"]
                                )
                                for s in selected_rel_items
                            }
                            res = client.bulk_apply_relation_merges(project, mapping, collapse_edges=cb_bulk_collapse)
                            st.session_state[sel_rel_pairs_key] = set()
                            dup_msg = f" Đã hợp nhất {res.merged_duplicate_edges} cạnh trùng bộ ba." if getattr(res, "merged_duplicate_edges", 0) > 0 else ""
                            st.success(
                                f"Đã gộp thành công {res.applied_count} quan hệ trong danh sách. "
                                f"Cập nhật {len(res.affected_edge_ids)} cạnh bị ảnh hưởng.{dup_msg}"
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

                    if ract_col2.button(
                        f"🚫 Đánh dấu {len(selected_rel_items)} cặp là Khác quan hệ",
                        width='stretch',
                        key="btn_bulk_mark_not_dup_rel",
                        help="Lưu vào danh sách 'Khác quan hệ' để không gợi ý lại trong các lần rà soát sau.",
                    ):
                        client.mark_relation_pairs_not_duplicate_bulk(
                            project,
                            [(s["relation_a"], s["relation_b"]) for s in selected_rel_items],
                            note="Người duyệt xác nhận khác quan hệ",
                        )
                        st.session_state[sel_rel_pairs_key] = set()
                        st.success(f"Đã đánh dấu {len(selected_rel_items)} cặp là khác quan hệ.")
                        st.rerun()
        else:
            st.info("Không có cặp quan hệ nghi trùng nào ở ngưỡng tương đồng hiện tại.")


def _render_manual_relation_and_dedup_section(project: dict, client: FrontendClient) -> None:
    """Phần 3: Bàn gộp quan hệ thủ công và tiện ích khử trùng cạnh lặp."""
    with st.container(border=True):
        st.markdown("#### 🔀 3. Bàn Gộp Quan hệ Thủ công (Manual Relation Merge)")
        st.caption("Cho phép chọn thủ công nhiều quan hệ nguồn và chỉ định một quan hệ đích chuẩn để hợp nhất toàn bộ dữ kiện.")
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        rel_merge_nonce_key = f"_rel_merge_nonce_{proj_id}"
        rel_merge_nonce = int(st.session_state.get(rel_merge_nonce_key) or 0)
        all_rels = sorted(list(dict.fromkeys(
            str(e.get("relation", "")).strip()
            for e in project.get("edges", [])
            if str(e.get("relation", "")).strip()
        )))
        if len(all_rels) < 2:
            st.info("Dự án cần có ít nhất 2 quan hệ khác nhau để thực hiện gộp thủ công.")
        else:
            sync_keyed_multiselect("manual_rel_merge_sources", all_rels, [], (proj_id, rel_merge_nonce))
            st.session_state["manual_rel_merge_sources"] = [
                r for r in st.session_state.get("manual_rel_merge_sources", []) if r in all_rels
            ]
            m_rel_sources = st.multiselect(
                "Chọn các quan hệ nguồn cần gộp (2 hoặc nhiều hơn)",
                options=all_rels,
                key="manual_rel_merge_sources",
            )
            if m_rel_sources:
                with st.expander("🔍 Xem Ngữ cảnh & Bằng chứng của các Quan hệ Nguồn Đã Chọn", expanded=False):
                    render_relation_provenance_panel(project, m_rel_sources)
            m_rel_col1, m_rel_col2 = st.columns([1.5, 1.5])
            target_options = [""] + m_rel_sources + [r for r in all_rels if r not in m_rel_sources]
            sync_keyed_choice("manual_rel_merge_target_select", target_options, "", (proj_id, rel_merge_nonce))
            if st.session_state.get("manual_rel_merge_target_select") not in target_options:
                st.session_state["manual_rel_merge_target_select"] = ""
            m_target_choice = m_rel_col1.selectbox(
                "Chọn quan hệ đích từ danh sách hiện có",
                options=target_options,
                format_func=lambda x: "— Chọn từ danh sách —" if not x else x,
                key="manual_rel_merge_target_select",
            )
            sync_keyed_value("manual_rel_merge_target_input", "", (proj_id, rel_merge_nonce))
            m_target_custom = m_rel_col2.text_input(
                "Hoặc nhập tên quan hệ đích chuẩn mới",
                key="manual_rel_merge_target_input",
            )
            effective_target = m_target_custom.strip() or m_target_choice.strip()
            if effective_target:
                st.caption(f"Quan hệ chuẩn đích sẽ nhận: `{effective_target}`")

            sync_keyed_value("cb_manual_rel_collapse", False, (proj_id, rel_merge_nonce))
            cb_manual_collapse = st.checkbox(
                "Tự động hợp nhất các cạnh trùng bộ ba (dồn bằng chứng đầy đủ)",
                key="cb_manual_rel_collapse",
            )
            if st.button(
                f"🔗 Gộp {len(m_rel_sources)} quan hệ đã chọn về `{effective_target or '...'}`",
                disabled=len(m_rel_sources) < 1 or not effective_target,
                type="primary",
                width='stretch',
                key="btn_apply_manual_rel_merge",
            ):
                try:
                    res = client.apply_relation_merge(
                        project, m_rel_sources, effective_target, collapse_edges=cb_manual_collapse
                    )
                    bump_sync_nonce(rel_merge_nonce_key)
                    reset_edc_state_if_project_changed(project, force=True)
                    reset_curation_state_if_project_changed(project, force=True)
                    dup_msg = f" Đã hợp nhất {res.merged_duplicate_edges} cạnh trùng bộ ba." if getattr(res, "merged_duplicate_edges", 0) > 0 else ""
                    st.success(
                        f"Đã gộp thành công {res.applied_count} quan hệ về `{effective_target}` · "
                        f"Cập nhật {len(res.affected_edge_ids)} cạnh.{dup_msg}"
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    dup_groups = compute_apparent_duplicate_edge_groups(project.get("edges", []))
    if dup_groups:
        total_dup_edges = sum(g.get("count", 1) - 1 for g in dup_groups)
        with st.container(border=True):
            st.markdown("#### ✨ 3. Khử trùng Cạnh Lặp (Triples Deduplication Utility)")
            st.warning(
                f"⚠️ Đang có **{len(dup_groups)}** nhóm cạnh có cùng bộ ba (Nguồn – Quan hệ – Đích), "
                f"tương ứng **{total_dup_edges}** cạnh bị trùng lặp."
            )
            if st.button(
                f"⚡ Hợp nhất ngay {total_dup_edges} cạnh trùng lặp (Dồn bằng chứng an toàn)",
                type="primary",
                key="btn_collapse_dup_edges_direct",
                help="Giữ lại cạnh chuẩn nhất cho từng bộ ba, dồn toàn bộ bằng chứng nguyên văn và xóa các cạnh dư thừa.",
            ):
                res = client.collapse_duplicate_edges(project)
                reset_edc_state_if_project_changed(project, force=True)
                reset_curation_state_if_project_changed(project, force=True)
                st.success(f"Đã hợp nhất thành công {res.merged_duplicate_edges} cạnh trùng bộ ba!")
                st.rerun()


def _render_relation_merge_history_section(project: dict, client: FrontendClient) -> None:
    """Phần 4: Lịch sử gộp quan hệ, bảng relation_aliases/relation_redirects và khôi phục snapshot."""
    rel_merges = list(reversed(project.get("relation_merges", [])))
    rel_redirects = project.get("relation_redirects", {})
    rel_aliases = project.get("relation_aliases", {})
    expander_title = f"📜 Lịch sử Gộp Quan hệ ({len(rel_merges)} phiên) & Biến thể Ngữ nghĩa Aliases ({len(rel_aliases)} quan hệ)"
    with st.expander(expander_title, expanded=False):
        if rel_aliases:
            st.caption("Từ đồng nghĩa / Biến thể ngữ nghĩa đã tích lũy (`relation_aliases` cho LLM & Retrieval):")
            st.json(rel_aliases)
        if rel_redirects:
            st.caption("Bảng ánh xạ phẳng `relation_redirects` (`variant_relation -> canonical_relation`):")
            st.json(rel_redirects)
        if not rel_merges:
            st.info("Chưa có phiên gộp quan hệ nào trong dự án.")
        else:
            st.dataframe(
                [
                    {
                        "Mã phiên": m.get("merge_id", ""),
                        "Thời điểm": m.get("at", ""),
                        "Quan hệ đích": m.get("canonical_relation", ""),
                        "Quan hệ nguồn gộp": ", ".join(m.get("source_relations", [])),
                        "Số cạnh cập nhật": m.get("affected_edge_count", 0),
                    }
                    for m in rel_merges
                ],
                width='stretch',
                hide_index=True,
            )
            latest_snap = str(rel_merges[0].get("snapshot_path") or "")
            if latest_snap and Path(latest_snap).exists():
                confirm_undo = st.checkbox(
                    f"Tôi xác nhận khôi phục toàn dự án về snapshot ngay trước phiên gộp `{rel_merges[0].get('merge_id', '')}`",
                    key="chk_restore_rel_merge_snap",
                )
                if st.button(
                    "⏪ Khôi phục toàn dự án về Snapshot trước phiên gộp quan hệ này",
                    disabled=not confirm_undo,
                    key="btn_restore_rel_merge_snap",
                ):
                    proj_id = str(project.get("project_id") or project.get("name") or "default")
                    client.restore_snapshot(project, latest_snap)
                    bump_sync_nonce(f"_rel_merge_nonce_{proj_id}")
                    st.session_state["chk_restore_rel_merge_snap"] = False
                    reset_edc_state_if_project_changed(project, force=True)
                    reset_curation_state_if_project_changed(project, force=True)
                    st.success("Đã khôi phục dự án về snapshot trước khi gộp quan hệ.")
                    st.rerun()


def render_relation_merge_tab(
    project: dict,
    client: FrontendClient,
    m_state: dict[str, Any],
) -> None:
    """Nội dung Tab 2: Phát hiện quan hệ nghi trùng, Gộp quan hệ hàng loạt & Bàn gộp quan hệ thủ công."""
    _render_ai_semantic_relation_section(project, client)
    st.divider()
    _render_fuzzy_relation_matching_section(project, client, m_state)
    st.divider()
    _render_manual_relation_and_dedup_section(project, client)
    _render_relation_merge_history_section(project, client)
