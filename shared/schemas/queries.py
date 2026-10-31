"""Hợp đồng dữ liệu đọc phân trang (Read Model DTOs) cho SQLite và Streamlit UI.
Quy định cấu trúc trả về nhẹ (Lightweight DTOs) để UI không phải nạp full project.json.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ProjectHeaderDTO:
    """Metadata tóm tắt của dự án để hiển thị Sidebar / Selector."""
    project_id: str
    name: str
    folder: str
    schema_version: str = "2.0.0"
    saved_at: str = ""
    documents_count: int = 0
    nodes_count: int = 0
    edges_count: int = 0
    storage_mode: str = "legacy_json"


@dataclass(frozen=True)
class PageDTO(Generic[T]):
    """Khung trang dữ liệu tổng quát cho truy vấn danh sách có phân trang và revision."""
    items: list[T]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    source_revision: str = ""
    next_cursor: str | None = None


@dataclass(frozen=True)
class EdgeRowDTO:
    """Bản ghi nhẹ của một cạnh quan hệ hiển thị trong bảng kiểm duyệt (Tab 4)."""
    id: str
    project_id: str
    source: str
    target: str
    relation: str
    status: str
    doc_id: str = ""
    chunk_number: int = 0
    evidence_found: bool = False
    evidence: str = ""
    start_char: int | None = None
    end_char: int | None = None


@dataclass(frozen=True)
class NodeRowDTO:
    """Bản ghi nhẹ của một thực thể trong bảng quản lý thực thể."""
    id: str
    project_id: str
    name: str
    kind: str
    aliases: list[str] = field(default_factory=list)
    degree: int = 0


@dataclass(frozen=True)
class ProposalRowDTO:
    """Bản ghi nhẹ của một đề xuất EDC hiển thị trong bảng EDC (Tab 4)."""
    id: str
    project_id: str
    kind: str
    name: str
    status: str
    canonical_name: str = ""
    alignment_score: float = 0.0
    impact_edges_count: int = 0
    impact_nodes_count: int = 0

