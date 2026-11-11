"""Router quản lý Projects, Model discovery và Health check."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.dependencies import FacadeDep, ProjectDep
from shared.schemas.project import ProjectSummaryDTO

router = APIRouter(tags=["Projects & System"])


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Tên dự án mới")
    description: str = Field(default="", description="Mô tả dự án")


@router.get("/health", summary="Kiểm tra trạng thái hệ thống")
def get_health(facade: FacadeDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "KG Studio Pro Commercial & ML API v2",
        "modes": facade.available_extraction_modes(),
    }


@router.get("/models", summary="Danh sách Embedding Models khả dụng")
def list_models(facade: FacadeDep) -> dict[str, Any]:
    return {"models": facade.list_embedding_models()}


@router.get("/projects", summary="Danh sách tất cả dự án trong hệ thống")
def list_projects(facade: FacadeDep) -> dict[str, list[dict[str, Any]]]:
    names = facade.list_projects()
    summaries = []
    for n in names:
        summ = facade.sqlite_repo.get_project_summary(n)
        if not summ.project_id:
            summ = facade.sqlite_repo.get_project_summary(facade.load_project(n))
        summaries.append(summ.to_dict())
    return {"projects": summaries}


@router.post("/projects", summary="Tạo mới một dự án Knowledge Graph", status_code=status.HTTP_201_CREATED)
def create_project(body: CreateProjectRequest, facade: FacadeDep) -> dict[str, Any]:
    names = facade.list_projects()
    if body.name in names:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dự án '{body.name}' đã tồn tại.",
        )
    proj = facade.project_repo.empty_project(body.name)
    facade.save_project(proj)
    summary = facade.sqlite_repo.get_project_summary(proj)
    return {"status": "created", "project": summary.to_dict()}


@router.get("/projects/{project_name}", summary="Lấy thông tin chi tiết một dự án")
def get_project_summary(project_name: str, project: ProjectDep, facade: FacadeDep) -> dict[str, Any]:
    summary = facade.sqlite_repo.get_project_summary(project)
    return {"project": summary.to_dict()}
