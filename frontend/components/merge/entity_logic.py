"""Logic xem trước, áp dụng gộp thực thể và định dạng thông báo từ điển dự án."""
from __future__ import annotations

from typing import Any

from backend.domain.catalogs.service import compute_project_revision
from frontend.client import FrontendClient, get_client
from frontend.state.session import (
    get_curation_section_state,
    store_entity_merge_preview,
)
from shared.schemas.curation import (
    CurationResultDTO,
    EntityMergePreviewDTO,
    EntityMergeRequestDTO,
)
from shared.text_utils import uid


def build_entity_merge_preview(
    project: dict,
    *,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> EntityMergePreviewDTO:
    """Tạo bản xem trước tác động gộp thực thể từ trạng thái bàn gộp hiện tại và lưu vào session."""
    svc_client = client or get_client()
    m_state = get_curation_section_state(project, "merge", state_store)
    req_id = uid()
    req = EntityMergeRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        member_ids=list(m_state.get("member_ids") or []),
        keep_id=str(m_state.get("keep_id") or ""),
        canonical_name=str(m_state.get("canonical_name") or ""),
        canonical_kind=str(m_state.get("canonical_kind") or ""),
        kind_resolution_note=str(m_state.get("kind_resolution_note") or ""),
        canonical_description=str(m_state.get("canonical_description") or ""),
        alias_overrides=m_state.get("alias_overrides"),
        note=str(m_state.get("note") or ""),
        expected_revision=compute_project_revision(project),
        request_id=req_id,
    )
    preview = svc_client.preview_entity_merge(project, req)
    store_entity_merge_preview(project, preview, request_id=req_id, state_store=state_store)
    return preview


def execute_entity_merge_apply(
    project: dict,
    *,
    collapse_edges: bool = True,
    client: FrontendClient | None = None,
    state_store: dict[str, Any] | None = None,
) -> CurationResultDTO:
    """Thực thi gộp thực thể sau khi đã xem trước hợp lệ và làm sạch bàn gộp."""
    svc_client = client or get_client()
    m_state = get_curation_section_state(project, "merge", state_store)
    active_prev = m_state.get("active_preview")
    if not active_prev:
        raise ValueError("Vui lòng chạy Xem trước tác động gộp trước khi xác nhận gộp thực thể.")

    raw_aliases = list(m_state.get("alias_overrides") or m_state.get("aliases") or [])
    req = EntityMergeRequestDTO(
        project_id=str(project.get("project_id") or project.get("name") or ""),
        member_ids=list(active_prev.get("member_ids") or m_state.get("member_ids") or []),
        keep_id=str(active_prev.get("keep_id") or m_state.get("keep_id") or ""),
        canonical_name=str(active_prev.get("canonical_name") or m_state.get("canonical_name") or ""),
        canonical_kind=str(active_prev.get("canonical_kind") or m_state.get("canonical_kind") or ""),
        kind_resolution_note=str(m_state.get("kind_resolution_note") or ""),
        canonical_description=str(active_prev.get("canonical_description") or m_state.get("canonical_description") or ""),
        aliases=raw_aliases,
        note=str(m_state.get("note") or ""),
        expected_revision=str(active_prev.get("revision") or compute_project_revision(project)),
        request_id=str(m_state.get("preview_request_id") or uid()),
        collapse_edges=collapse_edges,
    )
    result = svc_client.apply_entity_merge(project, req, preview=active_prev)
    m_state["member_ids"] = []
    m_state["keep_id"] = ""
    m_state["canonical_name"] = ""
    m_state["canonical_kind"] = ""
    m_state["kind_resolution_note"] = ""
    m_state["canonical_description"] = ""
    m_state["note"] = ""
    m_state["sync_nonce"] = int(m_state.get("sync_nonce") or 0) + 1
    m_state["active_preview"] = None
    m_state["preview_request_id"] = ""
    m_state["last_result"] = result.to_dict()
    return result


def _format_gazetteer_merge_notice(project: dict) -> str:
    """Tạo thông báo các bí danh vừa được tự động học vào Từ điển Dự án sau khi gộp thực thể."""
    latest = (project.get("entity_merges") or [{}])[-1]
    added = [str(a) for a in (latest.get("gazetteer_aliases_added") or []) if str(a).strip()]
    if not added:
        return ""
    if len(added) <= 4:
        items_str = ", ".join(f"`{a}`" for a in added)
        return f" 📚 Đã thêm {len(added)} bí danh vào Từ điển Dự án ({items_str})."
    preview_str = ", ".join(f"`{a}`" for a in added[:3])
    return f" 📚 Đã thêm {len(added)} bí danh vào Từ điển Dự án ({preview_str}, ...)."
