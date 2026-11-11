"""Hợp đồng dữ liệu đọc phân trang (Read Model DTOs) cho SQLite và Streamlit UI (Pydantic v2)."""
from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import Field

from shared.schemas.base import SchemaModel

T = TypeVar("T")


class ProjectHeaderDTO(SchemaModel):
    """Metadata tóm tắt của dự án để hiển thị Sidebar / Selector."""
    project_id: str = ""
    name: str = ""
    folder: str = ""
    schema_version: str = "2.0.0"
    saved_at: str = ""
    documents_count: int = 0
    nodes_count: int = 0
    edges_count: int = 0
    storage_mode: str = "legacy_json"


class PageDTO(SchemaModel, Generic[T]):
    """Khung trang dữ liệu tổng quát cho truy vấn danh sách có phân trang và revision."""
    items: list[T] = Field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 1
    source_revision: str = ""
    next_cursor: str | None = None

    @classmethod
    def from_items(
        cls,
        items: list[T],
        total_count: int,
        page: int = 1,
        page_size: int = 20,
        source_revision: str = "",
    ) -> PageDTO[T]:
        ps = max(1, page_size)
        tp = max(1, (total_count + ps - 1) // ps)
        return cls(
            items=items,
            total_count=total_count,
            page=max(1, page),
            page_size=ps,
            total_pages=tp,
            source_revision=source_revision,
        )


class EdgeRowDTO(SchemaModel):
    """Bản ghi nhẹ của một cạnh quan hệ hiển thị trong bảng kiểm duyệt (Tab 4)."""
    id: str = ""
    project_id: str = ""
    source: str = ""
    target: str = ""
    relation: str = ""
    status: str = ""
    doc_id: str = ""
    chunk_number: int = 0
    evidence_found: bool = False
    evidence: str = ""
    start_char: int | None = None
    end_char: int | None = None


class NodeRowDTO(SchemaModel):
    """Bản ghi nhẹ của một thực thể trong bảng quản lý thực thể."""
    id: str = ""
    project_id: str = ""
    name: str = ""
    kind: str = ""
    aliases: list[str] = Field(default_factory=list)
    degree: int = 0


class ProposalRowDTO(SchemaModel):
    """Bản ghi nhẹ của một đề xuất EDC hiển thị trong bảng EDC (Tab 4)."""
    id: str = ""
    project_id: str = ""
    kind: str = ""
    name: str = ""
    status: str = ""
    canonical_name: str = ""
    alignment_score: float = 0.0
    impact_edges_count: int = 0
    impact_nodes_count: int = 0
