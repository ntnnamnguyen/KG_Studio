"""Mô hình dữ liệu (DTO) cho Trang 5: Kiểm duyệt dữ kiện, Hồ sơ thực thể và Gộp thực thể."""
from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .base import SchemaModel

REJECTION_REASON_CODES: dict[str, str] = {
    "wrong_entity": "Sai thực thể",
    "wrong_relation_or_direction": "Sai quan hệ / chiều",
    "insufficient_evidence": "Không đủ bằng chứng",
    "duplicate_fact": "Dữ kiện trùng",
    "out_of_scope": "Không thuộc phạm vi",
    "other": "Khác",
}

NON_SEMANTIC_REJECTION_CODES: frozenset[str] = frozenset({"duplicate_fact", "out_of_scope"})


class CurationQueryDTO(SchemaModel):
    project_id: str = ""
    section: str = "edges"
    filters: dict[str, Any] = Field(default_factory=dict)
    sort_by: str = "default"
    sort_desc: bool = False
    page: int = 1
    page_size: int = 50

    @field_validator("page", mode="before")
    @classmethod
    def _validate_page(cls, v: Any) -> int:
        try:
            return max(1, int(v))
        except (TypeError, ValueError):
            return 1

    @field_validator("page_size", mode="before")
    @classmethod
    def _validate_page_size(cls, v: Any) -> int:
        try:
            return max(1, int(v))
        except (TypeError, ValueError):
            return 50


class EdgeReviewDecisionDTO(SchemaModel):
    edge_id: str = ""
    action: str = ""
    reason_code: str = ""
    note: str = ""
    override_reason: str = ""
    override_method: str = ""
    self_loop_confirmed: bool = False
    reviewer: str = "human_reviewer"


class CurationReviewRequestDTO(SchemaModel):
    project_id: str = ""
    expected_revision: str = ""
    request_id: str = ""
    decisions: list[EdgeReviewDecisionDTO] = Field(default_factory=list)
    apply_mode: str = "all_or_nothing"
    is_batch: bool = True
    actor: str = "human_reviewer"
    filter_summary: dict[str, Any] = Field(default_factory=dict)
    allow_schema_bypass: bool = False
    auto_sync_catalog: bool = True


class CurationPreviewDTO(SchemaModel):
    preview_id: str = ""
    project_id: str = ""
    revision: str = ""
    catalog_hash: str = ""
    request_hash: str = ""
    locked_edge_ids: list[str] = Field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    excluded_processed_count: int = 0
    item_previews: list[dict[str, Any]] = Field(default_factory=list)
    batch_errors: list[str] = Field(default_factory=list)
    can_apply_all: bool = False
    can_apply_valid_only: bool = False


class EntityEditRequestDTO(SchemaModel):
    project_id: str = ""
    node_id: str = ""
    expected_revision: str = ""
    request_id: str = ""
    name: str | None = None
    kind: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    note: str = ""
    actor: str = "human_reviewer"

    @field_validator("aliases", mode="before")
    @classmethod
    def _validate_aliases(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            return [x.strip() for x in v.split(";") if x.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return None


class EdgeEditRequestDTO(SchemaModel):
    project_id: str = ""
    edge_id: str = ""
    expected_revision: str = ""
    request_id: str = ""
    source: str | None = None
    target: str | None = None
    relation: str | None = None
    evidence: str | None = None
    doc_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    note: str = ""
    actor: str = "human_reviewer"


class EntityMergeRequestDTO(SchemaModel):
    project_id: str = ""
    member_ids: list[str] = Field(default_factory=list)
    keep_id: str = ""
    canonical_name: str = ""
    canonical_kind: str = ""
    kind_resolution_note: str = ""
    canonical_description: str = ""
    aliases: list[str] = Field(default_factory=list)
    note: str = ""
    expected_revision: str = ""
    request_id: str = ""
    actor: str = "human_reviewer"
    collapse_edges: bool = False

    @field_validator("aliases", mode="before")
    @classmethod
    def _validate_aliases(cls, v: Any) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(";") if x.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []


class EntityMergePreviewDTO(SchemaModel):
    preview_id: str = ""
    project_id: str = ""
    revision: str = ""
    catalog_hash: str = ""
    request_hash: str = ""
    member_ids: list[str] = Field(default_factory=list)
    keep_id: str = ""
    drop_ids: list[str] = Field(default_factory=list)
    valid: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking_proposal_ids: list[str] = Field(default_factory=list)
    has_kind_conflict: bool = False
    distinct_kinds: list[str] = Field(default_factory=list)
    has_description_conflict: bool = False
    distinct_descriptions: list[str] = Field(default_factory=list)
    merged_node_preview: dict[str, Any] = Field(default_factory=dict)
    affected_edge_count: int = 0
    changed_endpoint_count: int = 0
    invalidated_approved_count: int = 0
    new_self_loop_ids: list[str] = Field(default_factory=list)
    apparent_duplicate_groups: list[dict[str, Any]] = Field(default_factory=list)
    edge_changes: list[dict[str, Any]] = Field(default_factory=list)


class CurationResultDTO(SchemaModel):
    batch_id: str = ""
    request_id: str = ""
    project_id: str = ""
    operation: str = ""
    status: str = ""
    apply_mode: str = "all_or_nothing"
    revision_before: str = ""
    revision_after: str = ""
    applied_ids: list[str] = Field(default_factory=list)
    skipped_ids: list[str] = Field(default_factory=list)
    applied_count: int = 0
    skipped_count: int = 0
    item_results: list[dict[str, Any]] = Field(default_factory=list)
    affected_edge_ids: list[str] = Field(default_factory=list)
    changed_endpoint_count: int = 0
    merged_duplicate_edges: int = 0
    snapshot_path: str = ""
    sync_status: str = "synced"
    sync_error: str = ""
    idempotent_replay: bool = False
    errors: list[str] = Field(default_factory=list)
