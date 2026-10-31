"""Client giao tiếp giữa Frontend (Streamlit) và Backend Facade / REST API."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request

from backend.facade import KGStudioFacade, get_facade
from shared.schemas.curation import (
    CurationPreviewDTO,
    CurationResultDTO,
    CurationReviewRequestDTO,
    EdgeEditRequestDTO,
    EntityEditRequestDTO,
    EntityMergePreviewDTO,
    EntityMergeRequestDTO,
)
from shared.schemas.edc import (
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
)


class FrontendClient:
    def __init__(self, api_base_url: str = "", facade: KGStudioFacade | None = None) -> None:
        self.api_base_url = (api_base_url or "").rstrip("/")
        self.facade = facade or get_facade()

    def get_embedding_models(self) -> list[dict]:
        if self.api_base_url:
            try:
                with request.urlopen(f"{self.api_base_url}/api/v1/models", timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("models", [])
            except Exception:
                pass
        return self.facade.list_embedding_models()

    def retrieve_schema_preview(self, project: dict, chunk_text: str) -> dict[str, list[dict]]:
        return self.facade.retrieve_schema_for_chunk(project, chunk_text)

    def rank_alignment_candidates(self, project: dict, kind: str, open_name: str, open_definition: str) -> list[dict]:
        return self.facade.rank_alignment_candidates(project, kind, open_name, open_definition)

    def refresh_proposal_candidates(
        self,
        project: dict,
        proposal_ids: list[str],
        kind: str | None = None,
        *,
        save: bool = True,
    ) -> dict[str, Any]:
        return self.facade.refresh_proposal_candidates(project, proposal_ids, kind=kind, save=save)

    def run_target_alignment_on_pending(
        self,
        project: dict,
        *,
        proposal_ids: list[str] | None = None,
        kind: str | None = None,
    ) -> dict:
        return self.facade.run_target_alignment_on_pending(project, proposal_ids=proposal_ids, kind=kind)

    def preview_proposal_decisions(
        self,
        project: dict,
        req: BulkReviewRequestDTO | dict,
    ) -> BulkReviewPreviewDTO:
        return self.facade.preview_proposal_decisions(project, req)

    def apply_proposal_decisions(
        self,
        project: dict,
        req: BulkReviewRequestDTO | dict,
        *,
        preview: BulkReviewPreviewDTO | dict | None = None,
    ) -> BulkReviewResultDTO:
        return self.facade.apply_proposal_decisions(project, req, preview=preview)

    def decide_single_proposal(
        self,
        project: dict,
        proposal_id: str,
        action: str,
        canonical_name: str = "",
        definition: str = "",
        note: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        self.facade.create_snapshot(project)
        impact = self.facade.decide_proposal(
            project,
            proposal_id,
            action,
            canonical_name,
            definition,
            note,
            description,
        )
        self.facade.save_project(project)
        return impact

    def restore_snapshot(self, project: dict, snapshot_path: str | Path) -> dict:
        return self.facade.restore_snapshot(project, Path(snapshot_path))

    def resync_sqlite(self, project: dict) -> dict[str, Any]:
        return self.facade.resync_sqlite(project)

    def preview_curation_decisions(
        self,
        project: dict,
        req: CurationReviewRequestDTO | dict,
    ) -> CurationPreviewDTO:
        return self.facade.preview_curation_decisions(project, req)

    def apply_curation_decisions(
        self,
        project: dict,
        req: CurationReviewRequestDTO | dict,
        *,
        preview: CurationPreviewDTO | dict | None = None,
    ) -> CurationResultDTO:
        return self.facade.apply_curation_decisions(project, req, preview=preview)

    def edit_edge_fact(
        self,
        project: dict,
        req: EdgeEditRequestDTO | dict,
    ) -> CurationResultDTO:
        return self.facade.edit_edge_fact(project, req)

    def edit_entity_profile(
        self,
        project: dict,
        req: EntityEditRequestDTO | dict,
    ) -> CurationResultDTO:
        return self.facade.edit_entity_profile(project, req)

    def select_evidence_span(
        self,
        project: dict,
        edge_id: str,
        start_char: int,
        end_char: int,
        *,
        actor: str = "human_reviewer",
    ) -> dict[str, Any]:
        return self.facade.select_evidence_span(project, edge_id, start_char, end_char, actor=actor, save=True)

    def mark_pair_not_duplicate(
        self,
        project: dict,
        node_a_id: str,
        node_b_id: str,
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> dict[str, Any]:
        return self.facade.mark_pair_not_duplicate(project, node_a_id, node_b_id, note=note, actor=actor, save=True)

    def preview_entity_merge(
        self,
        project: dict,
        req: EntityMergeRequestDTO | dict,
    ) -> EntityMergePreviewDTO:
        return self.facade.preview_entity_merge(project, req)

    def apply_entity_merge(
        self,
        project: dict,
        req: EntityMergeRequestDTO | dict,
        *,
        preview: EntityMergePreviewDTO | dict | None = None,
    ) -> CurationResultDTO:
        return self.facade.apply_entity_merge(project, req, preview=preview)

    def apply_bulk_entity_merges(
        self,
        project: dict,
        pairs: list[dict | tuple[str, str]],
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.apply_bulk_entity_merges(project, pairs, note=note, actor=actor)

    def relation_duplicate_suggestions(
        self,
        project: dict,
        fuzzy_threshold: float = 0.75,
        *,
        include_dismissed: bool = False,
    ) -> list[dict]:
        return self.facade.relation_duplicate_suggestions(
            project, fuzzy_threshold=fuzzy_threshold, include_dismissed=include_dismissed
        )

    def apply_relation_merge(
        self,
        project: dict,
        source_relations: list[str],
        target_relation: str,
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.apply_relation_merge(
            project, source_relations, target_relation, note=note, actor=actor
        )

    def bulk_apply_relation_merges(
        self,
        project: dict,
        mappings: list[dict | tuple[str, str]],
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.bulk_apply_relation_merges(project, mappings, note=note, actor=actor)

    def mark_relation_pair_not_duplicate(
        self,
        project: dict,
        rel_a: str,
        rel_b: str,
        note: str = "",
    ) -> dict:
        return self.facade.mark_relation_pair_not_duplicate(project, rel_a, rel_b, note=note)

    def export_training_datasets(self, project: dict) -> dict:
        return self.facade.export_training_datasets(project)


_CLIENT: FrontendClient | None = None


def get_client() -> FrontendClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = FrontendClient()
    return _CLIENT
