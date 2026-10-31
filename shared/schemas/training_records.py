"""Lược đồ bản ghi dữ liệu huấn luyện (Training Datasets) xuất từ Active Learning sang ML Lab."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class SRTripletRecord:
    query_text: str
    positive_name: str
    positive_passage: str
    negative_name: str
    negative_passage: str
    project_id: str = ""
    doc_id: str = ""
    chunk_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CanonicalizationPairRecord:
    kind: str
    open_name: str
    open_definition: str
    query_text: str
    canonical_name: str
    canonical_passage: str
    negative_passages: list[str] = field(default_factory=list)
    action: str = "merge"
    project_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SFTInstructionRecord:
    system_prompt: str
    chunk_text: str
    retrieved_relations: list[str]
    target_json: dict
    project_id: str = ""
    doc_id: str = ""
    chunk_number: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

