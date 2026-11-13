"""Giao diện thiết lập Từ điển Bí danh Dự án (Project Domain Gazetteer) tại Bước 2 (Setup)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from backend.facade import get_facade


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


def render_gazetteer_setup_tab(project: dict) -> list[dict[str, Any]]:
    """Tab thiết lập Từ điển Bí danh tiền trích xuất tại Trang 2 (đồng bộ phong cách với Schema)."""
    facade = get_facade()
    entries = facade.list_gazetteer_entries(project)

    st.caption(
        "Khai báo trước các tên cổ, từ viết tắt và bí danh đặc thù của dự án (ví dụ: *Diên Hựu Tự* $\\rightarrow$ *Chùa Một Cột*, "
        "*Viện BTTLH* $\\rightarrow$ *Bảo tàng Dân tộc học Việt Nam*). Bước Ingestion sẽ tra cứu $O(1)$ để liên kết ngay từ đầu."
    )

    up_col, tpl_col = st.columns([2.2, 1.2])
    with up_col:
        up_gaz = st.file_uploader(
            "📥 Tải lên file JSON hoặc CSV Từ điển Bí danh (cột: alias, canonical_name, kind)",
            type=["json", "csv"],
            key="p02_up_gazetteer",
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
                    st.success(
                        f"Đã gộp thêm {res.applied_count} quy tắc mới từ `{up_gaz.name}` "
                        f"(giữ nguyên {res.skipped_count} mục đã có)!"
                    )
                    st.rerun()
            except Exception as exc:
                st.error(f"Lỗi gộp file từ điển: {exc}")

    # Chuẩn bị dữ liệu cho st.data_editor (luôn giữ khung cột rõ ràng ngay cả khi dự án mới chưa có mục nào)
    editor_rows = [
        {
            "alias": e.get("alias", ""),
            "canonical_name": e.get("canonical_name", ""),
            "kind": e.get("kind", ""),
            "source": e.get("source", "manual_editor"),
        }
        for e in entries
    ]
    if not editor_rows:
        editor_rows = [{"alias": "", "canonical_name": "", "kind": "", "source": "manual_editor"}]

    edited_gaz = st.data_editor(
        editor_rows,
        num_rows="dynamic",
        width="stretch",
        key="ed_gazetteer",
        column_config={
            "alias": st.column_config.TextColumn("Bí danh / Tên khác (alias)", required=True),
            "canonical_name": st.column_config.TextColumn("Tên chuẩn trong đồ thị (canonical_name)", required=True),
            "kind": st.column_config.TextColumn("Loại thực thể (kind)"),
            "source": st.column_config.TextColumn("Nguồn gốc (source)", disabled=True),
        },
    )

    clean_edited = [
        {
            "alias": str(r.get("alias") or "").strip(),
            "canonical_name": str(r.get("canonical_name") or "").strip(),
            "kind": str(r.get("kind") or "").strip(),
            "source": str(r.get("source") or "").strip(),
        }
        for r in edited_gaz
        if isinstance(r, dict)
        and str(r.get("alias") or "").strip()
        and str(r.get("canonical_name") or "").strip()
    ]

    act1, act2 = st.columns([2, 1])
    if act1.button("💾 Lưu Từ điển Bí danh", type="primary", key="p02_btn_save_gaz", width="stretch"):
        try:
            res = facade.replace_gazetteer_entries(
                project,
                clean_edited,
                source="manual_editor",
                expected_revision=facade.project_revision(project),
            )
            st.success(f"✅ Đã lưu {res.applied_count} quy tắc vào Từ điển Bí danh của dự án!")
            st.rerun()
        except Exception as exc:
            st.error(f"Lỗi khi lưu từ điển: {exc}")

    if entries and act2.button("🗑️ Xóa sạch từ điển", key="p02_btn_clear_gaz", width="stretch"):
        try:
            facade.clear_gazetteer(project, expected_revision=facade.project_revision(project))
            st.warning("Đã làm trống toàn bộ từ điển bí danh của dự án!")
            st.rerun()
        except Exception as exc:
            st.error(f"Lỗi khi xóa từ điển: {exc}")

    _render_download_buttons(project, facade, entries, key_prefix="p02_gaz")
    return clean_edited
