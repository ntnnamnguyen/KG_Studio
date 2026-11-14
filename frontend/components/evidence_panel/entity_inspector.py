"""Khung hiển thị và chỉnh sửa hồ sơ chi tiết của một thực thể độc lập (Trang 4)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.domain.catalogs.service import catalog_rows, compute_project_revision
from backend.domain.curation.service import find_node
from frontend.client import get_client
from frontend.state.session import (
    bump_sync_nonce,
    filter_edges_by_entity,
    get_curation_section_state,
    navigate_to_edc_proposal_from_curation,
    set_focused_edge,
    sync_keyed_choice,
    sync_keyed_value,
)
from shared.schemas.curation import EntityEditRequestDTO
from shared.text_utils import uid


def _render_entity_profile_form(project: dict, client: Any, node: dict) -> None:
    """Form chỉnh sửa tên, loại, bí danh, mô tả và nút nhảy sang đề xuất EDC liên quan."""
    approved_types = [str(t["name"]) for t in catalog_rows(project, "entity_types")]
    cur_kind = str(node.get("kind") or "")
    type_options = approved_types if cur_kind in approved_types else [cur_kind, *approved_types]
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    n_tag = (
        proj_id,
        str(node["id"]),
        compute_project_revision(project),
        int(st.session_state.get("_inspector_action_nonce") or 0),
    )

    with st.container(border=True):
        st.markdown("##### ✏️ Chỉnh sửa hồ sơ thực thể (Không cần gộp)")
        st.caption(
            "Quy tắc toàn vẹn (mục 8.2): Đổi tên hiển thị, bí danh hoặc mô tả sẽ giữ nguyên ID thực thể và trạng thái các cạnh. "
            "Nếu đổi **Loại thực thể**, các cạnh nối với thực thể này (trừ cạnh đã Loại bỏ) sẽ chuyển về **Cần kiểm tra**."
        )
        sync_keyed_value(f"ent_edit_name_{node['id']}", str(node.get("name", "")), n_tag)
        new_name = st.text_input("Tên chuẩn hiển thị", key=f"ent_edit_name_{node['id']}")
        sync_keyed_choice(f"ent_edit_kind_{node['id']}", type_options, cur_kind, n_tag)
        new_kind = st.selectbox(
            "Loại thực thể (chỉ cho phép chọn loại đã có trong danh mục đã duyệt)",
            type_options,
            key=f"ent_edit_kind_{node['id']}",
        )
        sync_keyed_value(f"ent_edit_aliases_{node['id']}", "; ".join(node.get("aliases", [])), n_tag)
        new_aliases_str = st.text_input(
            "Bí danh (phân tách bằng dấu chấm phẩy `;`)",
            key=f"ent_edit_aliases_{node['id']}",
        )
        sync_keyed_value(f"ent_edit_desc_{node['id']}", str(node.get("description") or ""), n_tag)
        new_desc = st.text_area(
            "Mô tả tổng hợp",
            height=90,
            key=f"ent_edit_desc_{node['id']}",
        )
        sync_keyed_value(f"ent_edit_note_{node['id']}", "", n_tag)
        edit_note = st.text_input("Ghi chú cập nhật hồ sơ", key=f"ent_edit_note_{node['id']}")

        if st.button("💾 Lưu hồ sơ thực thể", type="primary", key=f"btn_save_entity_{node['id']}"):
            try:
                req = EntityEditRequestDTO(
                    project_id=str(project.get("project_id") or project.get("name") or ""),
                    node_id=str(node["id"]),
                    name=new_name,
                    kind=new_kind,
                    description=new_desc,
                    aliases=[x.strip() for x in new_aliases_str.split(";") if x.strip()],
                    note=edit_note,
                    expected_revision=compute_project_revision(project),
                    request_id=uid(),
                )
                res = client.edit_entity_profile(project, req)
                e_state = get_curation_section_state(project, "entities")
                e_state["sel_editor_nonce"] = int(e_state.get("sel_editor_nonce") or 0) + 1
                bump_sync_nonce("_inspector_action_nonce")
                inv_count = len(res.affected_edge_ids)
                msg = f"Đã cập nhật hồ sơ thực thể `{new_name}`."
                if inv_count > 0:
                    msg += f" Đã chuyển {inv_count} cạnh liên kết về trạng thái Cần kiểm tra do đổi loại thực thể."
                st.success(msg)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        # Liên kết sang Trang 4 tab Lược đồ nếu thực thể còn đề xuất loại EDC
        prop_ids = list(node.get("schema_proposal_ids", []))
        if prop_ids:
            st.divider()
            st.caption("Đề xuất loại thực thể EDC liên quan:")
            for pid in prop_ids:
                if st.button(
                    f"🔗 Mở đề xuất loại `{pid}` ở Trang 4",
                    key=f"btn_jump_p04_from_node_{node['id']}_{pid}",
                ):
                    navigate_to_edc_proposal_from_curation(
                        project,
                        str(pid),
                        node_id=str(node["id"]),
                        section="entities",
                    )
                    st.rerun()


def _render_entity_connected_edges_card(
    project: dict,
    node: dict,
    nodes_by_id: dict[str, dict],
) -> None:
    """Hiển thị bảng các quan hệ đi ra/vào thực thể và lịch sử gộp vào thực thể."""
    with st.container(border=True):
        st.markdown("##### 🔗 Các quan hệ đi ra / đi vào thực thể này")
        connected = [
            e
            for e in project.get("edges", [])
            if e.get("source") == node["id"] or e.get("target") == node["id"]
        ]
        if not connected:
            st.info("Thực thể này hiện chưa có cạnh nối nào (Thực thể cô lập — bậc kết nối = 0).")
        else:
            st.dataframe(
                [
                    {
                        "ID cạnh": e["id"],
                        "Chiều": "Đi ra (Nguồn)" if e.get("source") == node["id"] else "Đi vào (Đích)",
                        "Nguồn": nodes_by_id.get(str(e.get("source", "")), {}).get("name", ""),
                        "Quan hệ": e.get("relation", ""),
                        "Đích": nodes_by_id.get(str(e.get("target", "")), {}).get("name", ""),
                        "Trạng thái": e.get("status", ""),
                    }
                    for e in connected
                ],
                width='stretch',
                hide_index=True,
            )
            je1, je2 = st.columns([2.0, 1.2])
            jump_eid = je1.selectbox(
                "Chọn cạnh để mở đối chiếu bằng chứng ở Khu vực A",
                [str(e["id"]) for e in connected],
                key=f"ent_jump_edge_sel_{node['id']}",
            )
            if je2.button("🔬 Mở cạnh này ở Khu vực A", width='stretch', key=f"btn_ent_jump_edge_{node['id']}"):
                filter_edges_by_entity(project, str(node["id"]))
                set_focused_edge(project, jump_eid)
                st.rerun()

        if node.get("merged_from"):
            st.divider()
            st.caption(f"Lịch sử gộp vào thực thể này ({len(node['merged_from'])} thực thể cũ):")
            st.dataframe(
                [
                    {
                        "ID cũ": m.get("id", ""),
                        "Tên cũ": m.get("name", ""),
                        "Loại cũ": m.get("kind", ""),
                        "Gộp lúc": m.get("merged_at", ""),
                    }
                    for m in node["merged_from"]
                ],
                width='stretch',
                hide_index=True,
            )


def render_entity_profile_inspector(project: dict, node_id: str) -> None:
    """Hiển thị và chỉnh sửa hồ sơ chi tiết của một thực thể độc lập ở Khu vực B (mục 6.2 & 6.3)."""
    node = find_node(project, node_id)
    if not node:
        st.info("Hãy chọn một thực thể trong bảng để xem và chỉnh sửa hồ sơ.")
        return

    client = get_client()
    nodes_by_id = {str(n["id"]): n for n in project.get("nodes", [])}
    st.markdown(f"#### 🏛️ Hồ sơ Thực thể: `{node.get('name', '')}` (`{node['id']}`)")

    col_form, col_edges = st.columns([1.05, 1.15])
    with col_form:
        _render_entity_profile_form(project, client, node)
    with col_edges:
        _render_entity_connected_edges_card(project, node, nodes_by_id)
