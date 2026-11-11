"""Mô hình dữ liệu (DTO) cho Trang 5: Kiểm duyệt dữ kiện, Hồ sơ thực thể và Gộp thực thể."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

REJECTION_REASON_CODES: dict[str, str] = {
    "wrong_entity": "Sai thực thể",
    "wrong_relation_or_direction": "Sai quan hệ / chiều",
    "insufficient_evidence": "Không đủ bằng chứng",
    "duplicate_fact": "Dữ kiện trùng",
    "out_of_scope": "Không thuộc phạm vi",
    "other": "Khác",
}

NON_SEMANTIC_REJECTION_CODES: frozenset[str] = frozenset({"duplicate_fact", "out_of_scope"})


@dataclass
class CurationQueryDTO:
    project_id: str
    section: str = "edges"
    filters: dict[str, Any] = field(default_factory=dict)
    sort_by: str = "default"
    sort_desc: bool = False
    page: int = 1
    page_size: int = 50

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | CurationQueryDTO) -> CurationQueryDTO:
        if isinstance(data, CurationQueryDTO):
            return data
        raw = data or {}
        return cls(
            project_id=str(raw.get("project_id", "")).strip(),
            section=str(raw.get("section", "edges") or "edges").strip(),
            filters=dict(raw.get("filters") or {}),
            sort_by=str(raw.get("sort_by", "default") or "default").strip(),
            sort_desc=bool(raw.get("sort_desc", False)),
            page=max(1, int(raw.get("page", 1) or 1)),
            page_size=max(1, int(raw.get("page_size", 50) or 50)),
        )


@dataclass
class EdgeReviewDecisionDTO:
    edge_id: str
    action: str
    reason_code: str = ""
    note: str = ""
    override_reason: str = ""
    override_method: str = ""
    self_loop_confirmed: bool = False
    reviewer: str = "human_reviewer"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | EdgeReviewDecisionDTO) -> EdgeReviewDecisionDTO:
        if isinstance(data, EdgeReviewDecisionDTO):
            return data
        raw = data or {}
        return cls(
            edge_id=str(raw.get("edge_id", "")).strip(),
            action=str(raw.get("action", "")).strip(),
            reason_code=str(raw.get("reason_code", "")).strip(),
            note=str(raw.get("note", "")),
            override_reason=str(raw.get("override_reason", "")),
            override_method=str(raw.get("override_method", "")),
            self_loop_confirmed=bool(raw.get("self_loop_confirmed", False)),
            reviewer=str(raw.get("reviewer", "human_reviewer") or "human_reviewer").strip(),
        )


@dataclass
class CurationReviewRequestDTO:
    project_id: str
    expected_revision: str = ""
    request_id: str = ""
    decisions: list[EdgeReviewDecisionDTO] = field(default_factory=list)
    apply_mode: str = "all_or_nothing"
    is_batch: bool = True
    actor: str = "human_reviewer"
    filter_summary: dict[str, Any] = field(default_factory=dict)
    allow_schema_bypass: bool = False
    auto_sync_catalog: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "expected_revision": self.expected_revision,
            "request_id": self.request_id,
            "decisions": [d.to_dict() for d in self.decisions],
            "apply_mode": self.apply_mode,
            "is_batch": self.is_batch,
            "actor": self.actor,
            "filter_summary": dict(self.filter_summary),
            "allow_schema_bypass": self.allow_schema_bypass,
            "auto_sync_catalog": self.auto_sync_catalog,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | CurationReviewRequestDTO) -> CurationReviewRequestDTO:
        if isinstance(data, CurationReviewRequestDTO):
            return data
        raw = data or {}
        return cls(
            project_id=str(raw.get("project_id", "")).strip(),
            expected_revision=str(raw.get("expected_revision", "")).strip(),
            request_id=str(raw.get("request_id", "")).strip(),
            decisions=[EdgeReviewDecisionDTO.from_dict(item) for item in raw.get("decisions", [])],
            apply_mode=str(raw.get("apply_mode", "all_or_nothing") or "all_or_nothing").strip(),
            is_batch=bool(raw.get("is_batch", True)),
            actor=str(raw.get("actor", "human_reviewer") or "human_reviewer").strip(),
            filter_summary=dict(raw.get("filter_summary") or {}),
            allow_schema_bypass=bool(raw.get("allow_schema_bypass", False)),
            auto_sync_catalog=bool(raw.get("auto_sync_catalog", True)),
        )


@dataclass
class CurationPreviewDTO:
    preview_id: str
    project_id: str
    revision: str
    catalog_hash: str
    request_hash: str
    locked_edge_ids: list[str] = field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    excluded_processed_count: int = 0
    item_previews: list[dict[str, Any]] = field(default_factory=list)
    batch_errors: list[str] = field(default_factory=list)
    can_apply_all: bool = False
    can_apply_valid_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | CurationPreviewDTO) -> CurationPreviewDTO:
        if isinstance(data, CurationPreviewDTO):
            return data
        raw = data or {}
        return cls(
            preview_id=str(raw.get("preview_id", "")),
            project_id=str(raw.get("project_id", "")),
            revision=str(raw.get("revision", "")),
            catalog_hash=str(raw.get("catalog_hash", "")),
            request_hash=str(raw.get("request_hash", "")),
            locked_edge_ids=list(raw.get("locked_edge_ids", [])),
            valid_count=int(raw.get("valid_count", 0) or 0),
            invalid_count=int(raw.get("invalid_count", 0) or 0),
            excluded_processed_count=int(raw.get("excluded_processed_count", 0) or 0),
            item_previews=list(raw.get("item_previews", [])),
            batch_errors=list(raw.get("batch_errors", [])),
            can_apply_all=bool(raw.get("can_apply_all", False)),
            can_apply_valid_only=bool(raw.get("can_apply_valid_only", False)),
        )


@dataclass
class EntityEditRequestDTO:
    project_id: str
    node_id: str
    expected_revision: str = ""
    request_id: str = ""
    name: str | None = None
    kind: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    note: str = ""
    actor: str = "human_reviewer"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | EntityEditRequestDTO) -> EntityEditRequestDTO:
        if isinstance(data, EntityEditRequestDTO):
            return data
        raw = data or {}
        aliases_val = raw.get("aliases")
        if isinstance(aliases_val, str):
            aliases_val = [x.strip() for x in aliases_val.split(";") if x.strip()]
        elif isinstance(aliases_val, list):
            aliases_val = [str(x).strip() for x in aliases_val if str(x).strip()]
        return cls(
            project_id=str(raw.get("project_id", "")).strip(),
            node_id=str(raw.get("node_id", "")).strip(),
            expected_revision=str(raw.get("expected_revision", "")).strip(),
            request_id=str(raw.get("request_id", "")).strip(),
            name=str(raw["name"]) if "name" in raw and raw["name"] is not None else None,
            kind=str(raw["kind"]) if "kind" in raw and raw["kind"] is not None else None,
            description=str(raw["description"]) if "description" in raw and raw["description"] is not None else None,
            aliases=aliases_val,
            note=str(raw.get("note", "")),
            actor=str(raw.get("actor", "human_reviewer") or "human_reviewer").strip(),
        )


@dataclass
class EdgeEditRequestDTO:
    project_id: str
    edge_id: str
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | EdgeEditRequestDTO) -> EdgeEditRequestDTO:
        if isinstance(data, EdgeEditRequestDTO):
            return data
        raw = data or {}
        return cls(
            project_id=str(raw.get("project_id", "")).strip(),
            edge_id=str(raw.get("edge_id", "")).strip(),
            expected_revision=str(raw.get("expected_revision", "")).strip(),
            request_id=str(raw.get("request_id", "")).strip(),
            source=str(raw["source"]) if "source" in raw and raw["source"] is not None else None,
            target=str(raw["target"]) if "target" in raw and raw["target"] is not None else None,
            relation=str(raw["relation"]) if "relation" in raw and raw["relation"] is not None else None,
            evidence=str(raw["evidence"]) if "evidence" in raw and raw["evidence"] is not None else None,
            doc_id=str(raw["doc_id"]) if "doc_id" in raw and raw["doc_id"] is not None else None,
            start_char=int(raw["start_char"]) if raw.get("start_char") is not None else None,
            end_char=int(raw["end_char"]) if raw.get("end_char") is not None else None,
            note=str(raw.get("note", "")),
            actor=str(raw.get("actor", "human_reviewer") or "human_reviewer").strip(),
        )


@dataclass
class EntityMergeRequestDTO:
    project_id: str
    member_ids: list[str] = field(default_factory=list)
    keep_id: str = ""
    canonical_name: str = ""
    canonical_kind: str = ""
    kind_resolution_note: str = ""
    canonical_description: str = ""
    aliases: list[str] = field(default_factory=list)
    note: str = ""
    expected_revision: str = ""
    request_id: str = ""
    actor: str = "human_reviewer"
    collapse_edges: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | EntityMergeRequestDTO) -> EntityMergeRequestDTO:
        if isinstance(data, EntityMergeRequestDTO):
            return data
        raw = data or {}
        raw_aliases = raw.get("aliases") or []
        if isinstance(raw_aliases, str):
            raw_aliases = [x.strip() for x in raw_aliases.split(";") if x.strip()]
        return cls(
            project_id=str(raw.get("project_id", "")).strip(),
            member_ids=[str(x).strip() for x in raw.get("member_ids", []) if str(x).strip()],
            keep_id=str(raw.get("keep_id", "")).strip(),
            canonical_name=str(raw.get("canonical_name", "")),
            canonical_kind=str(raw.get("canonical_kind", "")),
            kind_resolution_note=str(raw.get("kind_resolution_note", "")),
            canonical_description=str(raw.get("canonical_description", "")),
            aliases=[str(x).strip() for x in raw_aliases if str(x).strip()],
            note=str(raw.get("note", "")),
            expected_revision=str(raw.get("expected_revision", "")).strip(),
            request_id=str(raw.get("request_id", "")).strip(),
            actor=str(raw.get("actor", "human_reviewer") or "human_reviewer").strip(),
            collapse_edges=bool(raw.get("collapse_edges", False)),
        )


@dataclass
class EntityMergePreviewDTO:
    preview_id: str
    project_id: str
    revision: str
    catalog_hash: str
    request_hash: str
    member_ids: list[str] = field(default_factory=list)
    keep_id: str = ""
    drop_ids: list[str] = field(default_factory=list)
    valid: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocking_proposal_ids: list[str] = field(default_factory=list)
    has_kind_conflict: bool = False
    distinct_kinds: list[str] = field(default_factory=list)
    has_description_conflict: bool = False
    distinct_descriptions: list[str] = field(default_factory=list)
    merged_node_preview: dict[str, Any] = field(default_factory=dict)
    affected_edge_count: int = 0
    changed_endpoint_count: int = 0
    invalidated_approved_count: int = 0
    new_self_loop_ids: list[str] = field(default_factory=list)
    apparent_duplicate_groups: list[dict[str, Any]] = field(default_factory=list)
    edge_changes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | EntityMergePreviewDTO) -> EntityMergePreviewDTO:
        if isinstance(data, EntityMergePreviewDTO):
            return data
        raw = data or {}
        return cls(
            preview_id=str(raw.get("preview_id", "")),
            project_id=str(raw.get("project_id", "")),
            revision=str(raw.get("revision", "")),
            catalog_hash=str(raw.get("catalog_hash", "")),
            request_hash=str(raw.get("request_hash", "")),
            member_ids=list(raw.get("member_ids", [])),
            keep_id=str(raw.get("keep_id", "")),
            drop_ids=list(raw.get("drop_ids", [])),
            valid=bool(raw.get("valid", False)),
            errors=list(raw.get("errors", [])),
            warnings=list(raw.get("warnings", [])),
            blocking_proposal_ids=list(raw.get("blocking_proposal_ids", [])),
            has_kind_conflict=bool(raw.get("has_kind_conflict", False)),
            distinct_kinds=list(raw.get("distinct_kinds", [])),
            has_description_conflict=bool(raw.get("has_description_conflict", False)),
            distinct_descriptions=list(raw.get("distinct_descriptions", [])),
            merged_node_preview=dict(raw.get("merged_node_preview") or {}),
            affected_edge_count=int(raw.get("affected_edge_count", 0) or 0),
            changed_endpoint_count=int(raw.get("changed_endpoint_count", 0) or 0),
            invalidated_approved_count=int(raw.get("invalidated_approved_count", 0) or 0),
            new_self_loop_ids=list(raw.get("new_self_loop_ids", [])),
            apparent_duplicate_groups=list(raw.get("apparent_duplicate_groups", [])),
            edge_changes=list(raw.get("edge_changes", [])),
        )


@dataclass
class CurationResultDTO:
    batch_id: str
    request_id: str
    project_id: str
    operation: str
    status: str
    apply_mode: str = "all_or_nothing"
    revision_before: str = ""
    revision_after: str = ""
    applied_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    applied_count: int = 0
    skipped_count: int = 0
    item_results: list[dict[str, Any]] = field(default_factory=list)
    affected_edge_ids: list[str] = field(default_factory=list)
    changed_endpoint_count: int = 0
    merged_duplicate_edges: int = 0
    snapshot_path: str = ""
    sync_status: str = "synced"
    sync_error: str = ""
    idempotent_replay: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | CurationResultDTO) -> CurationResultDTO:
        if isinstance(data, CurationResultDTO):
            return data
        raw = data or {}
        return cls(
            batch_id=str(raw.get("batch_id", "")),
            request_id=str(raw.get("request_id", "")),
            project_id=str(raw.get("project_id", "")),
            operation=str(raw.get("operation", "")),
            status=str(raw.get("status", "")),
            apply_mode=str(raw.get("apply_mode", "all_or_nothing")),
            revision_before=str(raw.get("revision_before", "")),
            revision_after=str(raw.get("revision_after", "")),
            applied_ids=list(raw.get("applied_ids", [])),
            skipped_ids=list(raw.get("skipped_ids", [])),
            applied_count=int(raw.get("applied_count", 0) or 0),
            skipped_count=int(raw.get("skipped_count", 0) or 0),
            item_results=list(raw.get("item_results", [])),
            affected_edge_ids=list(raw.get("affected_edge_ids", [])),
            changed_endpoint_count=int(raw.get("changed_endpoint_count", 0) or 0),
            merged_duplicate_edges=int(raw.get("merged_duplicate_edges", 0) or 0),
            snapshot_path=str(raw.get("snapshot_path", "")),
            sync_status=str(raw.get("sync_status", "synced")),
            sync_error=str(raw.get("sync_error", "")),
            idempotent_replay=bool(raw.get("idempotent_replay", False)),
            errors=list(raw.get("errors", [])),
        )
