"""Router xử lý EDC Review (Duyệt đề xuất Schema/Relation/Entity Type)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.dependencies import FacadeDep, ProjectDep
from shared.schemas.edc import (
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
)

router = APIRouter(tags=["EDC Schema Proposals & Review"])


class RefreshCandidatesRequest(BaseModel):
    proposal_ids: list[str] = Field(default_factory=list, description="Danh sách proposal ID cần làm mới ứng viên")
    kind: str | None = Field(default=None, description="Loại đề xuất: 'relations' hoặc 'entity_types'")


def _validate_edc_scope(project_name: str, project: dict, req: BulkReviewRequestDTO) -> None:
    if not req.project_id:
        req.project_id = str(project.get("project_id") or project_name)
    else:
        valid_ids = {
            str(project.get("project_id") or "").strip(),
            str(project.get("name") or "").strip(),
            project_name.strip(),
        }
        valid_ids.discard("")
        if req.project_id not in valid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"project_id '{req.project_id}' trong request không khớp với dự án trên URL ('{project_name}')",
            )


@router.post("/projects/{project_name}/edc-review/preview", summary="Xem trước kết quả áp dụng duyệt hàng loạt đề xuất schema")
@router.post("/projects/{project_name}/edc/preview", summary="Xem trước kết quả áp dụng duyệt hàng loạt đề xuất schema")
def preview_edc_decisions(
    project_name: str,
    body: BulkReviewRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_edc_scope(project_name, project, body)
    preview = facade.preview_proposal_decisions(project, body)
    return {"preview": preview.to_dict()}


@router.post("/projects/{project_name}/edc-review/apply", summary="Áp dụng quyết định duyệt hàng loạt đề xuất schema")
@router.post("/projects/{project_name}/edc/apply", summary="Áp dụng quyết định duyệt hàng loạt đề xuất schema")
def apply_edc_decisions(
    project_name: str,
    body: BulkReviewRequestDTO,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    _validate_edc_scope(project_name, project, body)
    try:
        result = facade.apply_proposal_decisions(project, body)
        return {"result": result.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/edc-review/refresh-candidates", summary="Làm mới danh sách ứng viên gióng hàng cho các đề xuất")
@router.post("/projects/{project_name}/edc/refresh-candidates", summary="Làm mới danh sách ứng viên gióng hàng cho các đề xuất")
def refresh_candidates(
    project_name: str,
    body: RefreshCandidatesRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    summary = facade.refresh_proposal_candidates(
        project,
        body.proposal_ids,
        kind=body.kind,
        save=True,
    )
    return {"refresh_summary": summary}


@router.post("/projects/{project_name}/edc-review/resync", summary="Đồng bộ hóa lại dữ liệu schema giữa JSON và SQLite")
@router.post("/projects/{project_name}/edc/resync", summary="Đồng bộ hóa lại dữ liệu schema giữa JSON và SQLite")
def resync_sqlite(
    project_name: str,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        return facade.resync_sqlite(project)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
