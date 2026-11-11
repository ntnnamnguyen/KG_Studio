"""Router xử lý Curation (Kiểm duyệt dữ kiện, sửa thực thể, gộp thực thể và quan hệ)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.dependencies import FacadeDep, ProjectDep
from shared.schemas.curation import (
    CurationPreviewDTO,
    CurationResultDTO,
    CurationReviewRequestDTO,
    EdgeEditRequestDTO,
    EntityEditRequestDTO,
    EntityMergePreviewDTO,
    EntityMergeRequestDTO,
)

router = APIRouter(tags=["Knowledge Graph Curation & Refinement"])


class SelectSpanRequest(BaseModel):
    edge_id: str = Field(..., description="ID của cạnh/dữ kiện")
    start_char: int = Field(default=0, ge=0, description="Ký tự bắt đầu của bằng chứng")
    end_char: int = Field(default=0, ge=0, description="Ký tự kết thúc của bằng chứng")
    actor: str = Field(default="human_reviewer", description="Người thực hiện")


class NotDuplicateRequest(BaseModel):
    node_a_id: str = Field(..., description="ID thực thể thứ nhất")
    node_b_id: str = Field(..., description="ID thực thể thứ hai")
    note: str = Field(default="", description="Ghi chú xác nhận không trùng lặp")
    actor: str = Field(default="human_reviewer", description="Người thực hiện")


class RelationMergeRequest(BaseModel):
    source_relations: list[str] = Field(..., description="Danh sách quan hệ nguồn cần gộp")
    target_relation: str = Field(..., description="Quan hệ đích chuẩn hóa")
    collapse_edges: bool = Field(default=False, description="Tự động thu gọn các cạnh trùng")
    note: str = Field(default="", description="Ghi chú")
    actor: str = Field(default="human_reviewer", description="Người thực hiện")


class CollapseEdgesRequest(BaseModel):
    note: str = Field(default="", description="Ghi chú")
    actor: str = Field(default="human_reviewer", description="Người thực hiện")


def _validate_curation_scope(project_name: str, project: dict, project_id_req: str) -> None:
    if not project_id_req:
        return
    valid_ids = {
        str(project.get("project_id") or "").strip(),
        str(project.get("name") or "").strip(),
        project_name.strip(),
    }
    valid_ids.discard("")
    if project_id_req not in valid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"project_id '{project_id_req}' trong request không khớp với dự án trên URL ('{project_name}')",
        )


@router.post("/projects/{project_name}/curation/preview-edges", summary="Xem trước kết quả kiểm duyệt dữ kiện hàng loạt")
def preview_edges(
    project_name: str,
    body: CurationReviewRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_curation_scope(project_name, project, body.project_id)
    if not body.project_id:
        body.project_id = str(project.get("project_id") or project_name)
    preview = facade.preview_curation_decisions(project, body)
    return {"preview": preview.to_dict()}


@router.post("/projects/{project_name}/curation/apply-edges", summary="Áp dụng quyết định duyệt/từ chối dữ kiện")
def apply_edges(
    project_name: str,
    body: CurationReviewRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_curation_scope(project_name, project, body.project_id)
    if not body.project_id:
        body.project_id = str(project.get("project_id") or project_name)
    try:
        result = facade.apply_curation_decisions(project, body)
        return {"result": result.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/curation/edit-edge", summary="Chỉnh sửa chi tiết một cạnh/dữ kiện")
def edit_edge(
    project_name: str,
    body: EdgeEditRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_curation_scope(project_name, project, body.project_id)
    if not body.project_id:
        body.project_id = str(project.get("project_id") or project_name)
    try:
        result = facade.edit_edge_fact(project, body)
        return {"result": result.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/curation/edit-entity", summary="Chỉnh sửa hồ sơ một thực thể (tên, nhãn, alias)")
def edit_entity(
    project_name: str,
    body: EntityEditRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_curation_scope(project_name, project, body.project_id)
    if not body.project_id:
        body.project_id = str(project.get("project_id") or project_name)
    try:
        result = facade.edit_entity_profile(project, body)
        return {"result": result.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/curation/select-span", summary="Cập nhật vị trí bằng chứng (evidence span) cho cạnh")
def select_span(
    project_name: str,
    body: SelectSpanRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        ctx = facade.select_evidence_span(
            project,
            body.edge_id,
            body.start_char,
            body.end_char,
            actor=body.actor,
            save=True,
        )
        return {"evidence_context": ctx}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/curation/not-duplicate", summary="Đánh dấu 2 thực thể không phải là bản sao trùng lặp")
def mark_not_duplicate(
    project_name: str,
    body: NotDuplicateRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        pair_res = facade.mark_pair_not_duplicate(
            project,
            body.node_a_id,
            body.node_b_id,
            note=body.note,
            actor=body.actor,
            save=True,
        )
        return {"not_duplicate": pair_res}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/curation/preview-merge", summary="Xem trước kết quả gộp thực thể (Entity Merge)")
def preview_entity_merge(
    project_name: str,
    body: EntityMergeRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_curation_scope(project_name, project, body.project_id)
    if not body.project_id:
        body.project_id = str(project.get("project_id") or project_name)
    preview = facade.preview_entity_merge(project, body)
    return {"preview": preview.to_dict()}


@router.post("/projects/{project_name}/curation/apply-merge", summary="Thực hiện gộp các thực thể đồng nghĩa")
def apply_entity_merge(
    project_name: str,
    body: EntityMergeRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_curation_scope(project_name, project, body.project_id)
    if not body.project_id:
        body.project_id = str(project.get("project_id") or project_name)
    try:
        result = facade.apply_entity_merge(project, body)
        return {"result": result.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/curation/relation-merge", summary="Gộp quan hệ đồng nghĩa thành quan hệ chuẩn hóa")
def apply_relation_merge(
    project_name: str,
    body: RelationMergeRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        result = facade.apply_relation_merge(
            project,
            body.source_relations,
            body.target_relation,
            collapse_edges=body.collapse_edges,
            note=body.note,
            actor=body.actor,
        )
        return {"result": result.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/curation/collapse-duplicate-edges", summary="Thu gọn tất cả các cạnh trùng lặp trong đồ thị")
def collapse_edges(
    project_name: str,
    body: CollapseEdgesRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        result = facade.collapse_duplicate_edges(project, note=body.note, actor=body.actor)
        return {"result": result.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
