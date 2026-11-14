"""Giao diện thiết lập Từ điển Bí danh Dự án (Project Domain Gazetteer) tại Bước 2 (Setup)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from backend.facade import get_facade
from frontend.state.session import bump_sync_nonce


_TEMPLATE_PATH = Path("data/hanoi_historical_gazetteer.json")


def _render_template_preload_button(
    project: dict,
    facade: Any,
    *,
    button_key: str,
    label: str = "🏛️ Nạp từ điển Di tích Hà Nội mẫu",
) -> None:
    """Nút nạp bộ từ điển lịch sử Thăng Long - Hà Nội mẫu qua Commit Coordinator."""
    if not _TEMPLATE_PATH.exists():
        return
    if st.button(label, type="secondary", width="stretch", key=button_key):
        try:
            with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                t_data = json.load(f)
            res = facade.preload_gazetteer_template(
                project,
                template_entries=t_data,
                source="historical_template",
                expected_revision=facade.project_revision(project),
            )
            bump_sync_nonce("_catalog_editor_nonce")
            st.success(
                f"Đã nạp thêm {res.applied_count} quy tắc mới từ bộ từ điển mẫu "
                f"(bỏ qua {res.skipped_count} mục đã có)!"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Lỗi khi nạp từ điển mẫu: {exc}")


def _render_download_buttons(project: dict, facade: Any, entries: list[dict[str, Any]], *, key_prefix: str) -> None:
    """Nút tải về từ điển ở định dạng JSON và CSV (UTF-8 BOM cho Excel)."""
    if not entries:
        return
    proj_slug = project.get("name", "project")
    d1, d2 = st.columns(2)
    d1.download_button(
        "📤 Tải domain_gazetteer.json",
        data=facade.gazetteer_to_json_bytes(project),
        file_name=f"{proj_slug}_gazetteer.json",
        mime="application/json",
        key=f"{key_prefix}_dl_json",
        width="stretch",
    )
    d2.download_button(
        "📤 Tải domain_gazetteer.csv (Excel)",
        data=facade.gazetteer_to_csv_bytes(project),
        file_name=f"{proj_slug}_gazetteer.csv",
        mime="text/csv",
        key=f"{key_prefix}_dl_csv",
        width="stretch",
    )


def _collect_entity_kind_options(project: dict, grouped_rows: list[dict[str, Any]]) -> list[str]:
    """Tổng hợp danh sách loại thực thể hợp lệ cho SelectboxColumn từ entity_types và từ điển hiện có."""
    options: list[str] = []
    seen: set[str] = set()

    def _add(val: Any) -> None:
        text = str(val or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            options.append(text)

    for item in project.get("entity_types", []):
        _add(item.get("name") if isinstance(item, dict) else item)
    for row in grouped_rows:
        _add(row.get("kind"))
    return options


def render_gazetteer_setup_tab(project: dict) -> list[dict[str, str]]:
    """Tab thiết lập Từ điển Bí danh tiền trích xuất tại Trang 2 (gom nhóm 1 thực thể chuẩn — N bí danh)."""
    facade = get_facade()
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    cat_nonce = int(st.session_state.get("_catalog_editor_nonce") or 0)
    entries = facade.list_gazetteer_entries(project)
    grouped_rows = facade.list_grouped_gazetteer_entries(project)

    st.caption(
        f"Hiện có **{len(grouped_rows)}** chủ thể · **{len(entries)}** quy tắc bí danh. "
        "Mỗi dòng khai báo **một thực thể chuẩn** kèm **nhiều bí danh / tên khác** ngăn cách bằng dấu chấm phẩy `;` "
        "hoặc dấu gạch đứng `|` (ví dụ: *Trần Hưng Đạo* ← *Hưng Đạo Vương; Hưng Đạo Đại Vương | Quốc Công Tiết Chế*). "
        "Bước Ingestion tự bung phẳng và tra cứu $O(1)$."
    )

    up_col, tpl_col = st.columns([2.2, 1.2])
    with up_col:
        up_gaz = st.file_uploader(
            "📥 Tải lên file JSON hoặc CSV Từ điển Bí danh (cột: canonical_name, kind, aliases hoặc alias, canonical_name, kind)",
            type=["json", "csv"],
            key=f"p02_up_gazetteer_{proj_id}",
        )
    with tpl_col:
        st.markdown("<div style='height: 1.75rem'></div>", unsafe_allow_html=True)
        _render_template_preload_button(project, facade, button_key="p02_btn_preload_gaz")

    if up_gaz is not None:
        g_c1, g_c2 = st.columns(2)
        if g_c1.button("⚡ Nạp đè toàn bộ Từ điển", key="btn_apply_gaz_replace", width="stretch"):
            try:
                parsed = facade.parse_gazetteer_bytes(up_gaz.getvalue(), filename=up_gaz.name)
                if not parsed:
                    st.warning("Không tìm thấy quy tắc bí danh hợp lệ trong tệp tải lên.")
                else:
                    res = facade.replace_gazetteer_entries(
                        project,
                        parsed,
                        source="imported_file",
                        expected_revision=facade.project_revision(project),
                    )
                    bump_sync_nonce("_catalog_editor_nonce")
                    st.success(f"Đã nạp đè {res.applied_count} quy tắc bí danh từ `{up_gaz.name}`!")
                    st.rerun()
            except Exception as exc:
                st.error(f"Lỗi đọc file từ điển: {exc}")

        if g_c2.button("➕ Gộp thêm vào Từ điển hiện có", key="btn_apply_gaz_merge", width="stretch"):
            try:
                parsed = facade.parse_gazetteer_bytes(up_gaz.getvalue(), filename=up_gaz.name)
                if not parsed:
                    st.warning("Không tìm thấy quy tắc bí danh hợp lệ trong tệp tải lên.")
                else:
                    res = facade.merge_gazetteer_entries(
                        project,
                        parsed,
                        source="imported_file",
                        overwrite_existing=False,
                        expected_revision=facade.project_revision(project),
                    )
                    bump_sync_nonce("_catalog_editor_nonce")
                    st.success(
                        f"Đã gộp thêm {res.applied_count} quy tắc mới từ `{up_gaz.name}` "
                        f"(giữ nguyên {res.skipped_count} mục đã có)!"
                    )
                    st.rerun()
            except Exception as exc:
                st.error(f"Lỗi gộp file từ điển: {exc}")

    # Chuẩn bị dữ liệu gom nhóm cho st.data_editor (1 dòng = 1 thực thể chuẩn + nhiều bí danh ngăn cách ';' hoặc '|')
    editor_rows = [
        {
            "canonical_name": r.get("canonical_name", ""),
            "kind": r.get("kind", ""),
            "aliases": r.get("aliases", ""),
            "sources": r.get("sources", "manual_editor"),
        }
        for r in grouped_rows
    ]
    if not editor_rows:
        editor_rows = [{"canonical_name": "", "kind": "", "aliases": "", "sources": "manual_editor"}]

    kind_options = _collect_entity_kind_options(project, grouped_rows)
    kind_column = (
        st.column_config.SelectboxColumn(
            "Loại thực thể (kind)",
            options=[""] + kind_options,
            default="",
            format_func=lambda v: str(v) if str(v) else "(Không gắn loại)",
            help="Chọn loại thực thể từ Danh mục để tránh gõ sai chính tả hoặc lệch loại khi trích xuất.",
        )
        if kind_options
        else st.column_config.TextColumn("Loại thực thể (kind)")
    )

    edited_gaz = st.data_editor(
        editor_rows,
        num_rows="dynamic",
        width="stretch",
        key=f"ed_gazetteer_grouped_{proj_id}_{cat_nonce}",
        column_config={
            "canonical_name": st.column_config.TextColumn(
                "Tên chuẩn trong đồ thị (canonical_name)",
                required=True,
                help="Tên chính duy nhất của thực thể (ví dụ: Trần Hưng Đạo).",
            ),
            "kind": kind_column,
            "aliases": st.column_config.TextColumn(
                "Bí danh / Tên khác (ngăn cách ';' hoặc '|')",
                required=True,
                help="Nhập nhiều bí danh trên cùng một dòng, cách nhau bằng ';' hoặc '|' (ví dụ: Hưng Đạo Vương; Hưng Đạo Đại Vương).",
            ),
            "sources": st.column_config.TextColumn("Nguồn gốc", disabled=True),
        },
    )
    if kind_options:
        st.caption(
            "💡 Mẹo: Nhấp đúp (double-click) hoặc nhấn `Enter` vào ô **Loại thực thể (kind)** để mở danh sách chọn từ Danh mục Loại thực thể."
        )

    raw_rows = list(edited_gaz) if isinstance(edited_gaz, list) else edited_gaz.to_dict("records")
    validation_error = ""
    try:
        clean_edited = facade.expand_grouped_gazetteer_rows(raw_rows, strict_conflicts=True)
    except ValueError as exc:
        validation_error = str(exc)
        clean_edited = []

    st.session_state["_p02_gaz_validation_error"] = validation_error
    st.session_state[f"_p02_gaz_validation_error_{proj_id}"] = validation_error
    if validation_error:
        st.error(f"⚠️ {validation_error}")

    incomplete_canons = [
        str(r.get("canonical_name") or "").strip()
        for r in raw_rows
        if isinstance(r, dict)
        and str(r.get("canonical_name") or "").strip()
        and not str(r.get("aliases") or "").strip()
    ]

    act1, act2 = st.columns([2, 1])
    if act1.button("💾 Lưu Từ điển Bí danh", type="primary", key="p02_btn_save_gaz", width="stretch"):
        if validation_error:
            st.error(f"❌ Không thể lưu từ điển: {validation_error}")
        else:
            try:
                res = facade.replace_gazetteer_entries(
                    project,
                    clean_edited,
                    source="manual_editor",
                    expected_revision=facade.project_revision(project),
                )
                bump_sync_nonce("_catalog_editor_nonce")
                if incomplete_canons:
                    st.warning(
                        f"Đã lưu {res.applied_count} quy tắc bí danh. Lưu ý: bỏ qua {len(incomplete_canons)} dòng "
                        f"chỉ có tên chuẩn nhưng chưa nhập bí danh ({', '.join(incomplete_canons[:3])})."
                    )
                else:
                    st.success(f"✅ Đã lưu {res.applied_count} quy tắc bí danh vào Từ điển của dự án!")
                st.rerun()
            except Exception as exc:
                st.error(f"Lỗi khi lưu từ điển: {exc}")

    if entries and act2.button("🗑️ Xóa sạch từ điển", key="p02_btn_clear_gaz", width="stretch"):
        try:
            facade.clear_gazetteer(project, expected_revision=facade.project_revision(project))
            bump_sync_nonce("_catalog_editor_nonce")
            st.warning("Đã làm trống toàn bộ từ điển bí danh của dự án!")
            st.rerun()
        except Exception as exc:
            st.error(f"Lỗi khi xóa từ điển: {exc}")

    _render_download_buttons(project, facade, entries, key_prefix="p02_gaz")
    return clean_edited
