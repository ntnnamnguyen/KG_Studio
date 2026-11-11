"""Router xử lý Trích xuất tri thức (Extraction) và Schema Intelligence."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api.dependencies import FacadeDep, ProjectDep

router = APIRouter(tags=["Knowledge Extraction & Schema Intelligence"])


class RetrieveSchemaRequest(BaseModel):
    chunk_text: str = Field(..., description="Đoạn văn bản cần truy hồi schema liên quan")


class AlignTargetRequest(BaseModel):
    kind: str = Field(default="relations", description="Loại mục tiêu cần gióng hàng: 'relations' hoặc 'entity_types'")
    name: str = Field(..., description="Tên thực thể hoặc quan hệ mở cần gióng hàng")
    definition: str = Field(default="", description="Định nghĩa hoặc ngữ cảnh")


class AlignPendingRequest(BaseModel):
    proposal_ids: list[str] | None = Field(default=None, description="Danh sách proposal ID cần gióng hàng (None = tất cả pending)")
    kind: str | None = Field(default=None, description="'relations' hoặc 'entity_types'")


@router.post("/projects/{project_name}/retrieve-schema", summary="Truy hồi schema (Schema Retrieval) phù hợp với ngữ cảnh đoạn văn")
@router.post("/projects/{project_name}/extraction/retrieve-schema", summary="Truy hồi schema phù hợp với ngữ cảnh đoạn văn")
def retrieve_schema(
    project_name: str,
    body: RetrieveSchemaRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    retrieved = facade.retrieve_schema_for_chunk(project, body.chunk_text)
    return {"retrieved": retrieved}


@router.post("/projects/{project_name}/align-target", summary="Gióng hàng và xếp hạng ứng viên chuẩn hóa (Target Alignment)")
@router.post("/projects/{project_name}/extraction/align-target", summary="Gióng hàng và xếp hạng ứng viên chuẩn hóa")
def align_target(
    project_name: str,
    body: AlignTargetRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    candidates = facade.rank_alignment_candidates(project, body.kind, body.name, body.definition)
    return {"candidates": candidates}


@router.post("/projects/{project_name}/extraction/align-pending", summary="Chạy gióng hàng tự động cho các đề xuất đang chờ duyệt")
def align_pending(
    project_name: str,
    body: AlignPendingRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    result = facade.run_target_alignment_on_pending(
        project,
        proposal_ids=body.proposal_ids,
        kind=body.kind,
    )
    return {"alignment_result": result}
