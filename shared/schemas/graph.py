"""Mô hình dữ liệu Thực thể, Quan hệ, Bằng chứng và Nhật ký từng bước (Step Trace)."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any

from shared.constants import STATUS_PENDING


@dataclass
class NodeDTO:
    id: str
    name: str
    kind: str = "Chưa phân loại"
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    schema_proposal_ids: list[str] = field(default_factory=list)
    edc_observations: list[dict[str, Any]] = field(default_factory=list)
    merged_from: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        base = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "aliases": list(self.aliases),
            "documents": list(self.documents),
        }
        if self.schema_proposal_ids:
            base["schema_proposal_ids"] = list(self.schema_proposal_ids)
        if self.edc_observations:
            base["edc_observations"] = copy.deepcopy(self.edc_observations)
        if self.merged_from:
            base["merged_from"] = copy.deepcopy(self.merged_from)
        for k, v in self.extra.items():
            if k not in base:
                base[k] = copy.deepcopy(v)
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeDTO:
        known_keys = {
            "id",
            "name",
            "kind",
            "description",
            "aliases",
            "documents",
            "schema_proposal_ids",
            "edc_observations",
            "merged_from",
        }
        extra = {k: copy.deepcopy(v) for k, v in data.items() if k not in known_keys}
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            kind=str(data.get("kind", "Chưa phân loại") or "Chưa phân loại"),
            description=str(data.get("description", "")),
            aliases=list(data.get("aliases", [])),
            documents=list(data.get("documents", [])),
            schema_proposal_ids=list(data.get("schema_proposal_ids", [])),
            edc_observations=copy.deepcopy(data.get("edc_observations", [])),
            merged_from=copy.deepcopy(data.get("merged_from", [])),
            extra=extra,
        )


@dataclass
class EdgeDTO:
    id: str
    source: str
    target: str
    relation: str
    evidence: str
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
    schema_proposal_ids: list[str] = field(default_factory=list)
    edc_original: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "evidence": self.evidence,
            "evidence_found": self.evidence_found,
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "chunk_number": self.chunk_number,
            "status": self.status,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "page": self.page,
            "reviewed_at": self.reviewed_at,
            "override": self.override,
            "review_note": self.review_note,
        }
        if self.doc_fingerprint:
            base["doc_fingerprint"] = self.doc_fingerprint
        if self.match_method:
            base["match_method"] = self.match_method
        if self.override_reason:
            base["override_reason"] = self.override_reason
        if self.rejection_code:
            base["rejection_code"] = self.rejection_code
        if self.schema_proposal_ids:
            base["schema_proposal_ids"] = list(self.schema_proposal_ids)
        if self.edc_original:
            base["edc_original"] = copy.deepcopy(self.edc_original)
        for k, v in self.extra.items():
            if k not in base:
                base[k] = copy.deepcopy(v)
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EdgeDTO:
        known_keys = {
            "id",
            "source",
            "target",
            "relation",
            "evidence",
            "evidence_found",
            "doc_id",
            "doc_name",
            "chunk_number",
            "status",
            "start_char",
            "end_char",
            "page",
            "doc_fingerprint",
            "match_method",
            "reviewed_at",
            "override",
            "override_reason",
            "rejection_code",
            "review_note",
            "schema_proposal_ids",
            "edc_original",
        }
        extra = {k: copy.deepcopy(v) for k, v in data.items() if k not in known_keys}
        return cls(
            id=str(data.get("id", "")),
            source=str(data.get("source", "")),
            target=str(data.get("target", "")),
            relation=str(data.get("relation", "")),
            evidence=str(data.get("evidence", "")),
            evidence_found=bool(data.get("evidence_found", False)),
            doc_id=str(data.get("doc_id", "")),
            doc_name=str(data.get("doc_name", "")),
            chunk_number=int(data.get("chunk_number", 0) or 0),
            status=str(data.get("status", STATUS_PENDING) or STATUS_PENDING),
            start_char=int(data["start_char"]) if data.get("start_char") is not None else None,
            end_char=int(data["end_char"]) if data.get("end_char") is not None else None,
            page=int(data["page"]) if data.get("page") is not None else None,
            doc_fingerprint=str(data.get("doc_fingerprint", "")),
            match_method=str(data.get("match_method", "")),
            reviewed_at=str(data.get("reviewed_at", "")),
            override=bool(data.get("override", False)),
            override_reason=str(data.get("override_reason", "")),
            rejection_code=str(data.get("rejection_code", "")),
            review_note=str(data.get("review_note", "")),
            schema_proposal_ids=list(data.get("schema_proposal_ids", [])),
            edc_original=copy.deepcopy(data.get("edc_original", {})),
            extra=extra,
        )


@dataclass
class EvidenceDTO:
    found: bool
    text: str
    quote: str = ""
    before_text: str = ""
    after_text: str = ""
    page: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    match_method: str = ""
    ambiguous: bool = False
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepTraceDTO:
    step_name: str
    loop_index: int = 1
    duration_ms: int = 0
    summary: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
