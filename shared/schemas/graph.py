"""Mô hình dữ liệu Thực thể, Quan hệ, Bằng chứng và Nhật ký từng bước (Pydantic v2)."""
from __future__ import annotations

from typing import Any
from pydantic import Field

from shared.constants import STATUS_PENDING
from shared.schemas.base import SchemaModel


class NodeDTO(SchemaModel):
    id: str = ""
    name: str = ""
    kind: str = "Chưa phân loại"
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    schema_proposal_ids: list[str] = Field(default_factory=list)
    edc_observations: list[dict[str, Any]] = Field(default_factory=list)
    merged_from: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class EdgeDTO(SchemaModel):
    id: str = ""
    source: str = ""
    target: str = ""
    relation: str = ""
    evidence: str = ""
    evidence_found: bool = False
    doc_id: str = ""
    doc_name: str = ""
    chunk_number: int = 0
    status: str = STATUS_PENDING
    start_char: int | None = None
    end_char: int | None = None
    page: int | None = None
    doc_fingerprint: str = ""
    match_method: str = ""
    reviewed_at: str = ""
    override: bool = False
    override_reason: str = ""
    rejection_code: str = ""
    review_note: str = ""
    schema_proposal_ids: list[str] = Field(default_factory=list)
    edc_original: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class EvidenceDTO(SchemaModel):
    found: bool = False
    text: str = ""
    quote: str = ""
    before_text: str = ""
    after_text: str = ""
    page: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    match_method: str = ""
    ambiguous: bool = False
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""


class StepTraceDTO(SchemaModel):
    step_name: str = ""
    loop_index: int = 1
    duration_ms: int = 0
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
