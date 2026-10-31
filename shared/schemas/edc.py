"""Mô hình dữ liệu cho Đề xuất EDC, Target Alignment và Duyệt Hàng Loạt (Bulk Review)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AlignmentCandidateDTO:
    name: str
    definition: str = ""
    description: str = ""
    score: float = 0.0
    verified_by_llm: bool = False
    reason: str = ""
    catalog_hash: str = ""
    model_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = round(float(self.score), 4)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AlignmentCandidateDTO:
        raw = data or {}
        return cls(
            name=str(raw.get("name", "")),
            definition=str(raw.get("definition", "")),
            description=str(raw.get("description", "")),
            score=float(raw.get("score", 0.0) or 0.0),
            verified_by_llm=bool(raw.get("verified_by_llm", False)),
            reason=str(raw.get("reason", "")),
            catalog_hash=str(raw.get("catalog_hash", "")),
            model_fingerprint=str(raw.get("model_fingerprint", "")),
        )


@dataclass
class SchemaProposalDTO:
    id: str
    kind: str
    name: str
    definition: str = ""
    description: str = ""
    status: str = "pending"
    canonical_name: str = ""
    alignment_candidates: list[dict[str, Any]] = field(default_factory=list)
    auto_aligned: bool = False
    alignment_score: float = 0.0
    decision_origin: str = ""
    candidates_catalog_hash: str = ""
    candidates_model_fingerprint: str = ""
    candidates_refreshed_at: str = ""
    last_refresh_error: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)
    review_note: str = ""
    reviewed_at: str = ""
    batch_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposalDecisionDTO:
    proposal_id: str
    kind: str
    action: str
    canonical_name: str = ""
    definition: str = ""
    description: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | ProposalDecisionDTO) -> ProposalDecisionDTO:
        if isinstance(data, ProposalDecisionDTO):
            return data
        raw = data or {}
        return cls(
            proposal_id=str(raw.get("proposal_id", "")).strip(),
            kind=str(raw.get("kind", "")).strip(),
            action=str(raw.get("action", "")).strip(),
            canonical_name=str(raw.get("canonical_name", "")),
            definition=str(raw.get("definition", "")),
            description=str(raw.get("description", "")),
            note=str(raw.get("note", "")),
        )


@dataclass
class BulkReviewRequestDTO:
    project_id: str
    kind: str
    expected_revision: str
    request_id: str
    decisions: list[ProposalDecisionDTO] = field(default_factory=list)
    apply_mode: str = "all_or_nothing"
    actor: str = "human_reviewer"
    filter_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "kind": self.kind,
            "expected_revision": self.expected_revision,
            "request_id": self.request_id,
            "decisions": [d.to_dict() for d in self.decisions],
            "apply_mode": self.apply_mode,
            "actor": self.actor,
            "filter_summary": dict(self.filter_summary),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | BulkReviewRequestDTO) -> BulkReviewRequestDTO:
        if isinstance(data, BulkReviewRequestDTO):
            return data
        raw = data or {}
        decisions = [ProposalDecisionDTO.from_dict(item) for item in raw.get("decisions", [])]
        return cls(
            project_id=str(raw.get("project_id", "")).strip(),
            kind=str(raw.get("kind", "")).strip(),
            expected_revision=str(raw.get("expected_revision", "")).strip(),
            request_id=str(raw.get("request_id", "")).strip(),
            decisions=decisions,
            apply_mode=str(raw.get("apply_mode", "all_or_nothing") or "all_or_nothing").strip(),
            actor=str(raw.get("actor", "human_reviewer") or "human_reviewer").strip(),
            filter_summary=dict(raw.get("filter_summary") or {}),
        )


@dataclass
class BulkReviewPreviewDTO:
    preview_id: str
    project_id: str
    kind: str
    revision: str
    catalog_hash: str
    request_hash: str
    locked_proposal_ids: list[str] = field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    item_previews: list[dict[str, Any]] = field(default_factory=list)
    batch_errors: list[str] = field(default_factory=list)
    affected_node_ids: list[str] = field(default_factory=list)
    affected_edge_ids: list[str] = field(default_factory=list)
    direct_edge_ids: list[str] = field(default_factory=list)
    indirect_edge_ids: list[str] = field(default_factory=list)
    can_apply_all: bool = False
    can_apply_valid_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | BulkReviewPreviewDTO) -> BulkReviewPreviewDTO:
        if isinstance(data, BulkReviewPreviewDTO):
            return data
        raw = data or {}
        return cls(
            preview_id=str(raw.get("preview_id", "")),
            project_id=str(raw.get("project_id", "")),
            kind=str(raw.get("kind", "")),
            revision=str(raw.get("revision", "")),
            catalog_hash=str(raw.get("catalog_hash", "")),
            request_hash=str(raw.get("request_hash", "")),
            locked_proposal_ids=list(raw.get("locked_proposal_ids", [])),
            valid_count=int(raw.get("valid_count", 0) or 0),
            invalid_count=int(raw.get("invalid_count", 0) or 0),
            item_previews=list(raw.get("item_previews", [])),
            batch_errors=list(raw.get("batch_errors", [])),
            affected_node_ids=list(raw.get("affected_node_ids", [])),
            affected_edge_ids=list(raw.get("affected_edge_ids", [])),
            direct_edge_ids=list(raw.get("direct_edge_ids", [])),
            indirect_edge_ids=list(raw.get("indirect_edge_ids", [])),
            can_apply_all=bool(raw.get("can_apply_all", False)),
            can_apply_valid_only=bool(raw.get("can_apply_valid_only", False)),
        )


@dataclass
class BulkReviewResultDTO:
    batch_id: str
    request_id: str
    project_id: str
    kind: str
    status: str
    apply_mode: str = "all_or_nothing"
    revision_before: str = ""
    revision_after: str = ""
    applied_count: int = 0
    skipped_count: int = 0
    invalid_count: int = 0
    item_results: list[dict[str, Any]] = field(default_factory=list)
    affected_node_ids: list[str] = field(default_factory=list)
    affected_edge_ids: list[str] = field(default_factory=list)
    snapshot_path: str = ""
    sync_status: str = "synced"
    sync_error: str = ""
    vector_index_status: str = "valid"
    idempotent_replay: bool = False
    batch_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | BulkReviewResultDTO) -> BulkReviewResultDTO:
        if isinstance(data, BulkReviewResultDTO):
            return data
        raw = data or {}
        return cls(
            batch_id=str(raw.get("batch_id", "")),
            request_id=str(raw.get("request_id", "")),
            project_id=str(raw.get("project_id", "")),
            kind=str(raw.get("kind", "")),
            status=str(raw.get("status", "")),
            apply_mode=str(raw.get("apply_mode", "all_or_nothing")),
            revision_before=str(raw.get("revision_before", "")),
            revision_after=str(raw.get("revision_after", "")),
            applied_count=int(raw.get("applied_count", 0) or 0),
            skipped_count=int(raw.get("skipped_count", 0) or 0),
            invalid_count=int(raw.get("invalid_count", 0) or 0),
            item_results=list(raw.get("item_results", [])),
            affected_node_ids=list(raw.get("affected_node_ids", [])),
            affected_edge_ids=list(raw.get("affected_edge_ids", [])),
            snapshot_path=str(raw.get("snapshot_path", "")),
            sync_status=str(raw.get("sync_status", "synced")),
            sync_error=str(raw.get("sync_error", "")),
            vector_index_status=str(raw.get("vector_index_status", "valid")),
            idempotent_replay=bool(raw.get("idempotent_replay", False)),
            batch_errors=list(raw.get("batch_errors", [])),
        )
