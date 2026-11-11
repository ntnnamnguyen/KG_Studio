"""Router xử lý G-Retriever Subgraph QA, Xuất dữ liệu huấn luyện và Tích hợp Neo4j."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.dependencies import FacadeDep, ProjectDep

router = APIRouter(tags=["Graph Operations, G-Retriever QA & ML Exports"])


class SubgraphRetrievalRequest(BaseModel):
    query: str = Field(..., description="Câu hỏi hoặc truy vấn tìm kiếm đồ thị")
    method: str = Field(default="pcst", description="Thuật toán trích xuất: 'pcst', 'pagerank', 'bfs', 'subgraph'")
    max_edges: int = Field(default=20, ge=1, le=100, description="Số lượng cạnh tối đa trong đồ thị con")
    approved_only: bool = Field(default=True, description="Chỉ lấy các dữ kiện đã duyệt (Approved)")
    base_edge_cost: float = Field(default=0.35, description="Chi phí cơ sở cho thuật toán PCST")
    hub_penalty_alpha: float = Field(default=0.45, description="Hệ số phạt nút trung tâm (hub node)")
    expand_leaf_attributes: bool = Field(default=True, description="Mở rộng thuộc tính lá")


class QuestionAnsweringRequest(BaseModel):
    query: str = Field(..., description="Câu hỏi của người dùng")
    method: str = Field(default="pcst", description="Thuật toán truy hồi đồ thị con")
    approved_only: bool = Field(default=True, description="Chỉ dùng dữ kiện đã duyệt")
    max_edges: int = Field(default=18, ge=1, le=50, description="Số cạnh tối đa làm ngữ cảnh")
    provider: str = Field(default="DeepSeek", description="LLM Provider: DeepSeek hoặc Ollama")
    api_key: str = Field(default="", description="API Key (tùy chọn, mặc định lấy từ secrets.toml)")
    model: str = Field(default="deepseek-chat", description="Tên mô hình ngôn ngữ")
    temperature: float = Field(default=0.1, ge=0.0, le=1.0, description="Nhiệt độ sinh văn bản")


class Neo4jSyncRequest(BaseModel):
    uri: str = Field(default="bolt://localhost:7687", description="Địa chỉ máy chủ Neo4j")
    user: str = Field(default="neo4j", description="Tên người dùng Neo4j")
    password: str = Field(..., description="Mật khẩu máy chủ Neo4j")


@router.post("/projects/{project_name}/graph/retrieve-subgraph", summary="G-Retriever: Truy hồi đồ thị con liên quan nhất đến câu hỏi")
def retrieve_subgraph(
    project_name: str,
    body: SubgraphRetrievalRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        subgraph = facade.retrieve_subgraph(
            project,
            body.query,
            method=body.method,
            max_edges=body.max_edges,
            approved_only=body.approved_only,
            base_edge_cost=body.base_edge_cost,
            hub_penalty_alpha=body.hub_penalty_alpha,
            expand_leaf_attributes=body.expand_leaf_attributes,
        )
        return {
            "query": body.query,
            "method": body.method,
            "subgraph": subgraph.to_dict() if hasattr(subgraph, "to_dict") else dict(subgraph),
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/graph/answer-question", summary="G-Retriever QA: Trả lời câu hỏi dựa trên đồ thị tri thức")
def answer_question(
    project_name: str,
    body: QuestionAnsweringRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        res = facade.answer_question_with_graph(
            project,
            query=body.query,
            method=body.method,
            approved_only=body.approved_only,
            max_edges=body.max_edges,
            provider=body.provider,
            api_key=body.api_key,
            model=body.model,
            temperature=body.temperature,
        )
        return {"result": res}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/export-training-data", summary="Xuất Active Learning Training Datasets (JSONL)")
@router.post("/projects/{project_name}/graph/export-training-data", summary="Xuất Active Learning Training Datasets (JSONL)")
def export_training_data(
    project_name: str,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        report = facade.export_training_datasets(project)
        return {"export_report": report}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/projects/{project_name}/graph/sync-neo4j", summary="Đồng bộ đồ thị đã duyệt vào máy chủ Neo4j")
def sync_to_neo4j(
    project_name: str,
    body: Neo4jSyncRequest,
    project: ProjectDep,
    facade: FacadeDep,
) -> dict[str, Any]:
    try:
        sync_result = facade.sync_neo4j(project, body.uri, body.user, body.password)
        return {"neo4j_sync": sync_result}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
