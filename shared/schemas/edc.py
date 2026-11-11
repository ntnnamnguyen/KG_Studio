"""Mô hình dữ liệu cho Đề xuất EDC, Target Alignment và Duyệt Hàng Loạt (Pydantic v2)."""
from __future__ import annotations

from typing import Any
from pydantic import Field

from shared.schemas.base import SchemaModel


class AlignmentCandidateDTO(SchemaModel):
    name: str = ""
    definition: str = ""
    description: str = ""
    score: float = 0.0
    verified_by_llm: bool = False
    reason: str = ""
    catalog_hash: str = ""
    model_fingerprint: str = ""


class SchemaProposalDTO(SchemaModel):
    id: str = ""
    kind: str = ""
    name: str = ""
    definition: str = ""
    description: str = ""
    status: str = "pending"
    canonical_name: str = ""
    alignment_candidates: list[dict[str, Any]] = Field(default_factory=list)
    auto_aligned: bool = False
    alignment_score: float = 0.0
    decision_origin: str = ""
    candidates_catalog_hash: str = ""
    candidates_model_fingerprint: str = ""
    candidates_refreshed_at: str = ""
    last_refresh_error: str = ""
    observations: list[dict[str, Any]] = Field(default_factory=list)
    review_note: str = ""
    reviewed_at: str = ""
    batch_id: str = ""


class ProposalDecisionDTO(SchemaModel):
    proposal_id: str = ""
    kind: str = ""
    action: str = ""
    canonical_name: str = ""
    definition: str = ""
    description: str = ""
    note: str = ""


class BulkReviewRequestDTO(SchemaModel):
    project_id: str = ""
    kind: str = ""
    expected_revision: str = ""
    request_id: str = ""
    decisions: list[ProposalDecisionDTO] = Field(default_factory=list)
    apply_mode: str = "all_or_nothing"
    actor: str = "human_reviewer"
    filter_summary: dict[str, Any] = Field(default_factory=dict)


class BulkReviewPreviewDTO(SchemaModel):
    preview_id: str = ""
    project_id: str = ""
    kind: str = ""
    revision: str = ""
    catalog_hash: str = ""
    request_hash: str = ""
    locked_proposal_ids: list[str] = Field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    item_previews: list[dict[str, Any]] = Field(default_factory=list)
    batch_errors: list[str] = Field(default_factory=list)
    affected_node_ids: list[str] = Field(default_factory=list)
    affected_edge_ids: list[str] = Field(default_factory=list)
    direct_edge_ids: list[str] = Field(default_factory=list)
    indirect_edge_ids: list[str] = Field(default_factory=list)
    can_apply_all: bool = False
    can_apply_valid_only: bool = False


class BulkReviewResultDTO(SchemaModel):
    batch_id: str = ""
    request_id: str = ""
    project_id: str = ""
    kind: str = ""
    status: str = ""
    apply_mode: str = "all_or_nothing"
    revision_before: str = ""
    revision_after: str = ""
    applied_count: int = 0
    skipped_count: int = 0
    invalid_count: int = 0
    item_results: list[dict[str, Any]] = Field(default_factory=list)
    affected_node_ids: list[str] = Field(default_factory=list)
    affected_edge_ids: list[str] = Field(default_factory=list)
    snapshot_path: str = ""
    sync_status: str = "synced"
    sync_error: str = ""
    vector_index_status: str = "valid"
    idempotent_replay: bool = False
    batch_errors: list[str] = Field(default_factory=list)
