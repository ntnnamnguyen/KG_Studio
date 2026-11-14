"""Mô hình dữ liệu cấu hình Dự án và EDC+R (Pydantic v2)."""
from __future__ import annotations

from typing import Any
from pydantic import Field

from shared.constants import DEFAULT_EDC_PLUS_R_SETTINGS, MODE_FIXED
from shared.schemas.base import SchemaModel


class EDCPlusRSettingsDTO(SchemaModel):
    embedder_model: str = Field(default=DEFAULT_EDC_PLUS_R_SETTINGS["embedder_model"])
    top_k_relations: int = Field(default=DEFAULT_EDC_PLUS_R_SETTINGS["top_k_relations"], ge=1, le=100)
    top_k_entity_types: int = Field(default=DEFAULT_EDC_PLUS_R_SETTINGS["top_k_entity_types"], ge=1, le=80)
    auto_align_threshold: float = Field(default=DEFAULT_EDC_PLUS_R_SETTINGS["auto_align_threshold"], ge=0.50, le=0.99)
    candidate_threshold: float = Field(default=DEFAULT_EDC_PLUS_R_SETTINGS["candidate_threshold"], ge=0.10, le=0.95)
    refinement_loops: int = Field(default=DEFAULT_EDC_PLUS_R_SETTINGS["refinement_loops"], ge=1, le=3)
    enable_llm_verifier: bool = Field(default=DEFAULT_EDC_PLUS_R_SETTINGS["enable_llm_verifier"])


class ProjectSummaryDTO(SchemaModel):
    project_id: str = ""
    name: str = ""
    extraction_mode: str = MODE_FIXED
    documents_count: int = 0
    nodes_count: int = 0
    edges_count: int = 0
    approved_edges_count: int = 0
    pending_proposals_count: int = 0
    saved_at: str = ""
