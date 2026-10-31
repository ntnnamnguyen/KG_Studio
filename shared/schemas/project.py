"""Mô hình dữ liệu cấu hình Dự án và EDC+R."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from shared.constants import DEFAULT_EDC_PLUS_R_SETTINGS, MODE_FIXED


@dataclass
class EDCPlusRSettingsDTO:
    embedder_model: str = DEFAULT_EDC_PLUS_R_SETTINGS["embedder_model"]
    top_k_relations: int = DEFAULT_EDC_PLUS_R_SETTINGS["top_k_relations"]
    top_k_entity_types: int = DEFAULT_EDC_PLUS_R_SETTINGS["top_k_entity_types"]
    auto_align_threshold: float = DEFAULT_EDC_PLUS_R_SETTINGS["auto_align_threshold"]
    candidate_threshold: float = DEFAULT_EDC_PLUS_R_SETTINGS["candidate_threshold"]
    refinement_loops: int = DEFAULT_EDC_PLUS_R_SETTINGS["refinement_loops"]
    enable_llm_verifier: bool = DEFAULT_EDC_PLUS_R_SETTINGS["enable_llm_verifier"]

    @classmethod
    def from_dict(cls, data: dict | None) -> "EDCPlusRSettingsDTO":
        raw = dict(DEFAULT_EDC_PLUS_R_SETTINGS)
        if isinstance(data, dict):
            raw.update({k: v for k, v in data.items() if k in raw and v is not None})
        return cls(
            embedder_model=str(raw["embedder_model"]).strip() or "hybrid_vn:default",
            top_k_relations=max(1, min(50, int(raw["top_k_relations"]))),
            top_k_entity_types=max(1, min(50, int(raw["top_k_entity_types"]))),
            auto_align_threshold=max(0.50, min(0.99, float(raw["auto_align_threshold"]))),
            candidate_threshold=max(0.10, min(0.95, float(raw["candidate_threshold"]))),
            refinement_loops=max(1, min(3, int(raw["refinement_loops"]))),
            enable_llm_verifier=bool(raw["enable_llm_verifier"]),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectSummaryDTO:
    project_id: str
    name: str
    extraction_mode: str = MODE_FIXED
    documents_count: int = 0
    nodes_count: int = 0
    edges_count: int = 0
    approved_edges_count: int = 0
    pending_proposals_count: int = 0
    saved_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

