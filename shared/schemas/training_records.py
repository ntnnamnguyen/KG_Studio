"""Lược đồ bản ghi dữ liệu huấn luyện (Training Datasets) xuất từ Active Learning sang ML Lab (Pydantic v2)."""
from __future__ import annotations

from typing import Any
from pydantic import Field

from shared.schemas.base import SchemaModel


class SRTripletRecord(SchemaModel):
    query_text: str = ""
    positive_name: str = ""
    positive_passage: str = ""
    negative_name: str = ""
    negative_passage: str = ""
    project_id: str = ""
    doc_id: str = ""
    chunk_hash: str = ""


class CanonicalizationPairRecord(SchemaModel):
    kind: str = ""
    open_name: str = ""
    open_definition: str = ""
    query_text: str = ""
    canonical_name: str = ""
    canonical_passage: str = ""
    negative_passages: list[str] = Field(default_factory=list)
    action: str = "merge"
    project_id: str = ""


class SFTInstructionRecord(SchemaModel):
    system_prompt: str = ""
    chunk_text: str = ""
    retrieved_relations: list[str] = Field(default_factory=list)
    target_json: dict[str, Any] = Field(default_factory=dict)
    project_id: str = ""
    doc_id: str = ""
    chunk_number: int = 0
