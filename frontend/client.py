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
    def __init__(self, api_base_url: str | KGStudioFacade = "", facade: KGStudioFacade | None = None) -> None:
        if isinstance(api_base_url, KGStudioFacade):
            self.api_base_url = ""
            self.facade = api_base_url
        else:
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
        return self.facade.decide_single_proposal(
            project,
            proposal_id,
            action,
            canonical_name=canonical_name,
            definition=definition,
            note=note,
            description=description,
        )

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

    def mark_pairs_not_duplicate_bulk(
        self,
        project: dict,
        pairs: list[tuple[str, str] | list[str] | dict[str, Any]],
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> list[dict[str, Any]]:
        return self.facade.mark_pairs_not_duplicate_bulk(project, pairs, note=note, actor=actor, save=True)

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
        collapse_edges: bool = False,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.apply_bulk_entity_merges(
            project, pairs, collapse_edges=collapse_edges, note=note, actor=actor
        )

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
        collapse_edges: bool = False,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.apply_relation_merge(
            project, source_relations, target_relation, collapse_edges=collapse_edges, note=note, actor=actor
        )

    def bulk_apply_relation_merges(
        self,
        project: dict,
        mappings: list[dict | tuple[str, str]],
        *,
        collapse_edges: bool = False,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.bulk_apply_relation_merges(
            project, mappings, collapse_edges=collapse_edges, note=note, actor=actor
        )

    def collapse_duplicate_edges(
        self,
        project: dict,
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.collapse_duplicate_edges(project, note=note, actor=actor)

    def compute_apparent_duplicate_edge_groups(self, edges_or_project: list | dict) -> list[dict]:
        return self.facade.compute_apparent_duplicate_edge_groups(edges_or_project)

    def mark_relation_pair_not_duplicate(
        self,
        project: dict,
        rel_a: str,
        rel_b: str,
        note: str = "",
    ) -> dict:
        return self.facade.mark_relation_pair_not_duplicate(project, rel_a, rel_b, note=note)

    def mark_relation_pairs_not_duplicate_bulk(
        self,
        project: dict,
        pairs: list[tuple[str, str] | list[str] | dict[str, Any]],
        *,
        note: str = "",
    ) -> dict[str, Any]:
        return self.facade.mark_relation_pairs_not_duplicate_bulk(project, pairs, note=note, save=True)

    def preview_clustering_prompt(
        self,
        project: dict,
        kind: str = "relations",
        custom_instructions: str = "",
        scope: str = "top_60",
    ) -> str:
        return self.facade.preview_clustering_prompt(
            project, kind=kind, custom_instructions=custom_instructions, scope=scope
        )

    def scan_semantic_clusters(
        self,
        project: dict,
        kind: str = "relations",
        *,
        scope: str = "top_60",
        provider: str = "DeepSeek",
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        client: Any = None,
        custom_instructions: str = "",
        prompt_override: str = "",
    ) -> dict[str, Any]:
        return self.facade.scan_semantic_clusters(
            project,
            kind=kind,
            scope=scope,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            client=client,
            custom_instructions=custom_instructions,
            prompt_override=prompt_override,
        )

    def apply_semantic_clusters(
        self,
        project: dict,
        kind: str,
        approved_clusters: list[dict],
        *,
        collapse_duplicate_edges: bool = True,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        return self.facade.apply_semantic_clusters(
            project,
            kind=kind,
            approved_clusters=approved_clusters,
            collapse_duplicate_edges=collapse_duplicate_edges,
            note=note,
            actor=actor,
        )

    def export_training_datasets(self, project: dict) -> dict:
        return self.facade.export_training_datasets(project)

    def retrieve_subgraph(
        self,
        project: dict,
        query: str,
        *,
        method: str = "pcst",
        max_edges: int = 20,
        approved_only: bool = True,
        base_edge_cost: float = 0.35,
        hub_penalty_alpha: float = 0.45,
        expand_leaf_attributes: bool = True,
    ) -> Any:
        return self.facade.retrieve_subgraph(
            project,
            query,
            method=method,
            max_edges=max_edges,
            approved_only=approved_only,
            base_edge_cost=base_edge_cost,
            hub_penalty_alpha=hub_penalty_alpha,
            expand_leaf_attributes=expand_leaf_attributes,
        )

    def answer_question_with_graph(
        self,
        subgraph_or_project: Any,
        query: str = "",
        *,
        method: str = "pcst",
        approved_only: bool = True,
        max_edges: int = 18,
        provider: str = "DeepSeek",
        api_key: str = "",
        model: str = "deepseek-chat",
        base_url: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        max_input_tokens: int = 16000,
        max_output_tokens: int = 2048,
        client: Any = None,
        llm_client: Any = None,
    ) -> dict[str, Any]:
        return self.facade.answer_question_with_graph(
            subgraph_or_project,
            query,
            method=method,
            approved_only=approved_only,
            max_edges=max_edges,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            client=client,
            llm_client=llm_client,
        )

    def generate_qa_benchmark(
        self,
        project: dict,
        *,
        num_questions: int = 18,
        approved_only: bool = True,
    ) -> list[dict[str, Any]]:
        return self.facade.generate_qa_benchmark(project, num_questions=num_questions, approved_only=approved_only)

    def generate_training_qa_dataset(
        self,
        project: dict,
        *,
        max_samples: int = 2000,
        train_ratio: float = 0.80,
        val_ratio: float = 0.10,
        approved_only: bool = True,
    ) -> dict[str, Any]:
        return self.facade.generate_training_qa_dataset(
            project,
            max_samples=max_samples,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            approved_only=approved_only,
        )

    def paraphrase_qa_questions_with_llm(
        self,
        items: list[dict[str, Any]],
        *,
        provider: str = "DeepSeek",
        api_key: str = "",
        model: str = "deepseek-chat",
        base_url: str = "",
        client: Any = None,
        batch_size: int = 10,
    ) -> list[dict[str, Any]]:
        return self.facade.paraphrase_qa_questions_with_llm(
            items,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            client=client,
            batch_size=batch_size,
        )

    def evaluate_retrieval_methods(
        self,
        project: dict,
        benchmark_items: list[dict[str, Any]] | None = None,
        *,
        max_edges: int = 15,
        approved_only: bool = True,
    ) -> dict[str, Any]:
        return self.facade.evaluate_retrieval_methods(
            project,
            benchmark_items=benchmark_items,
            max_edges=max_edges,
            approved_only=approved_only,
        )

    def load_project_from_export_bytes(self, raw_bytes: bytes, filename: str = "") -> dict[str, Any]:
        return self.facade.load_project_from_export_bytes(raw_bytes, filename=filename)

    def extract_chunks_parallel(
        self,
        project: dict,
        tasks: list[tuple[dict, dict]],
        *,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 12000,
        max_workers: int = 3,
        on_progress: Any = None,
        save_after_chunk: bool = True,
    ) -> dict[str, Any]:
        return self.facade.extract_chunks_parallel(
            project,
            tasks,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            max_workers=max_workers,
            on_progress=on_progress,
            save_after_chunk=save_after_chunk,
        )


_CLIENT: FrontendClient | None = None


def get_client() -> FrontendClient:
    global _CLIENT
    if _CLIENT is None:
        import os
        api_url = os.environ.get("KG_STUDIO_API_URL", "").strip()
        from frontend.composition import get_ui_composition
        comp = get_ui_composition()
        _CLIENT = FrontendClient(api_base_url=api_url, facade=comp.facade)
    return _CLIENT
