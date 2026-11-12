"""Lớp Tương Thích Ngược (Compatibility Facade) cho KG Studio.
Theo chuẩn Quy tắc 5 trong AGENTS.md:
- Facade KHÔNG chứa nghiệp vụ transaction, snapshot hay domain logic trực tiếp.
- Mọi phương thức công khai đều là một lời gọi ủy quyền (1-line delegate) sang
  6 Application Services chuẩn trong `backend/modules/`.
"""
from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Callable

from backend.domain.catalogs.core import compute_project_revision
from backend.domain.extraction.base_engine import EngineOutput
from backend.domain.graph.g_retriever import SubgraphRetrievalResult
from backend.integrations.embedder_gateway import list_registered_models
from backend.integrations.llm import LLMGateway
from backend.modules.curation.application.service import CurationApplicationService
from backend.modules.extraction.application.service import ExtractionApplicationService
from backend.modules.graph_qa.application.service import GraphQAApplicationService
from backend.modules.projects.application.service import ProjectsApplicationService
from backend.modules.schema_intelligence.application.service import SchemaIntelligenceApplicationService
from backend.modules.training.application.service import TrainingApplicationService
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
from shared.schemas.project import EDCPlusRSettingsDTO
from shared.schemas.prompts import PreparedExtractionRequestDTO
from shared.secrets_manager import get_api_key


class KGStudioFacade:
    """Compatibility Forwarding Facade kết nối các consumer cũ tới 6 Application Services."""

    def __init__(
        self,
        *,
        container: Any | None = None,
        json_repo: Any | None = None,
        sqlite_repo: Any | None = None,
        vector_repo: Any | None = None,
        engine_registry: Any | None = None,
        exporter: Any | None = None,
    ) -> None:
        from backend.bootstrap import get_container
        app_c = container or (get_container() if json_repo is None and sqlite_repo is None and vector_repo is None else None)

        if app_c is not None:
            self._container = app_c
            self.json_repo = app_c.json_repo
            self.sqlite_repo = app_c.sqlite_repo
            self.vector_repo = app_c.vector_repo
            self.projects_service = app_c.projects_service
            self.schema_service = app_c.schema_service
            self.extraction_service = app_c.extraction_service
            self.curation_service = app_c.curation_service
            self.graph_qa_service = app_c.graph_qa_service
            self.training_service = app_c.training_service
        else:
            from backend.repositories.json_repo import JsonProjectRepository
            from backend.repositories.sqlite_repo import SQLiteProjectRepository
            from backend.repositories.vector_repo import VectorIndexRepository
            self.json_repo = json_repo or JsonProjectRepository()
            self.sqlite_repo = sqlite_repo or SQLiteProjectRepository()
            self.vector_repo = vector_repo or VectorIndexRepository()
            self.projects_service = ProjectsApplicationService(
                project_store=self.json_repo,
                read_projection=self.sqlite_repo,
                vector_repo=self.vector_repo,
            )
            self.schema_service = SchemaIntelligenceApplicationService(
                commit_coordinator=self.projects_service.commit_coordinator,
                vector_repo=self.vector_repo,
            )
            self.extraction_service = ExtractionApplicationService(
                engine_registry=engine_registry,
                llm_gateway=LLMGateway,
                schema_service=self.schema_service,
                project_store=self.json_repo,
                commit_coordinator=self.projects_service.commit_coordinator,
            )
            self.curation_service = CurationApplicationService(
                commit_coordinator=self.projects_service.commit_coordinator,
                project_store=self.json_repo,
            )
            self.graph_qa_service = GraphQAApplicationService()
            self.training_service = TrainingApplicationService(exporter=exporter)

        # Compatibility attributes for legacy inspection
        self.commit_coordinator = self.projects_service.commit_coordinator
        self.retriever = getattr(self.schema_service, "retriever", None)
        self.aligner = getattr(self.schema_service, "aligner", None)
        self.engine_registry = self.extraction_service.engine_registry
        self.exporter = self.training_service.exporter
        self._last_committed_revision: dict[str, str] = {}

    def _current_model_fingerprint(self, project: dict) -> str:
        """Lấy fingerprint của mô hình embedding hiện tại phục vụ tương thích ngược."""
        try:
            settings = self.get_edc_plus_r_settings(project)
            from backend.integrations.embedder_gateway import default_embedder
            embedder = default_embedder(settings.embedder_model)
            return getattr(embedder, "fingerprint", "") or ""
        except Exception:
            return ""

    def _sync_sqlite_safe(self, project: dict, result_dto: Any | None = None) -> tuple[str, str]:
        """Đồng bộ SQLite an toàn phục vụ tương thích ngược."""
        name = project.get("name", "")
        try:
            self.sqlite_repo.sync_from_project_dict(project)
            if name and hasattr(self.json_repo, "clear_sync_pending"):
                self.json_repo.clear_sync_pending(name)
            project["sync_pending"] = False
            project["sync_error"] = ""
            if result_dto is not None:
                result_dto.sync_status = "synced"
                result_dto.sync_error = ""
            return "synced", ""
        except Exception as exc:
            err_str = str(exc)
            if name and hasattr(self.json_repo, "mark_sync_pending"):
                self.json_repo.mark_sync_pending(name, err_str)
            project["sync_pending"] = True
            project["sync_error"] = err_str
            if result_dto is not None:
                result_dto.sync_status = "sync_pending"
                result_dto.sync_error = err_str
            return "sync_pending", err_str

    def _check_revision_conflict(
        self,
        proj_id: str,
        proj_name: str,
        project: dict,
        expected_revision: str,
    ) -> str:
        """Kiểm tra xung đột đa phiên phục vụ tương thích ngược."""
        mem_rev = compute_project_revision(project)
        if not expected_revision:
            return mem_rev
        last_committed_rev = self._last_committed_revision.get(proj_id)
        if last_committed_rev and last_committed_rev != mem_rev and expected_revision != last_committed_rev:
            raise ValueError(
                "Dự án đã được cập nhật bởi một phiên làm việc khác (revision mismatch). Vui lòng tải lại và xem trước lại."
            )
        return mem_rev

    # =========================================================================
    # 1. PHÂN HỆ PROJECTS (backend/modules/projects)
    # =========================================================================

    def get_project_lock(self, project_key: str) -> threading.RLock:
        return self.projects_service.get_project_lock(project_key)

    def list_projects(self) -> list[str]:
        return self.projects_service.list_projects()

    def list_project_headers(self) -> list[dict]:
        return self.projects_service.list_project_headers()

    def load_project(self, name: str) -> dict:
        return self.projects_service.load_project(name)

    def save_project(self, project: dict) -> Path:
        return self.projects_service.save_project(project)

    def resync_sqlite(self, project: dict) -> dict[str, Any]:
        return self.projects_service.resync_sqlite(project)

    def query_edges_page(self, project_or_id: dict | str, **kwargs: Any) -> dict[str, Any]:
        return self.projects_service.query_edges_page(project_or_id, **kwargs)

    def query_nodes_page(self, project_or_id: dict | str, **kwargs: Any) -> dict[str, Any]:
        return self.projects_service.query_nodes_page(project_or_id, **kwargs)

    def query_proposals_page(self, project_or_id: dict | str, **kwargs: Any) -> dict[str, Any]:
        return self.projects_service.query_proposals_page(project_or_id, **kwargs)

    def get_node_by_id(self, project_or_id: dict | str, node_id: str) -> dict | None:
        return self.projects_service.get_node_by_id(project_or_id, node_id)

    def get_edge_by_id(self, project_or_id: dict | str, edge_id: str) -> dict | None:
        return self.projects_service.get_edge_by_id(project_or_id, edge_id)

    def create_snapshot(self, project: dict) -> Path:
        return self.projects_service.create_snapshot(project)

    def list_snapshots(self, project: dict) -> list[Path]:
        return self.projects_service.list_snapshots(project)

    def restore_snapshot(self, project: dict, path: Path) -> dict:
        return self.projects_service.restore_snapshot(project, path)

    def project_revision(self, project: dict) -> str:
        return self.projects_service.project_revision(project)

    # =========================================================================
    # 2. PHÂN HỆ DOCUMENTS & EXTRACTION (backend/modules/extraction)
    # =========================================================================

    def add_document(self, project: dict, name: str, data: bytes, place_scope: str = "", source_label: str = "") -> tuple[bool, str]:
        return self.extraction_service.add_document(project, name, data, place_scope, source_label)

    def document_chunks(self, doc: dict, limit: int = 3200, overlap: int = 250) -> list[dict]:
        return self.extraction_service.document_chunks(doc)

    def available_extraction_modes(self) -> list[dict]:
        return self.engine_registry.available_modes()

    def get_active_prompt_version(self, project: dict, configuration_id: str | None = None) -> dict | None:
        return self.extraction_service.get_active_prompt_version(project, configuration_id or "")

    def get_active_prompt_content(self, project: dict, configuration_id: str | None = None) -> str:
        ver = self.get_active_prompt_version(project, configuration_id)
        return ver.get("content", "") if ver else ""

    def list_prompt_versions(self, project: dict, configuration_id: str | None = None) -> list[dict]:
        return self.extraction_service.list_prompt_versions(project, configuration_id or "")

    def get_prompt_version(self, project: dict, version_id: str) -> dict | None:
        return self.extraction_service.get_prompt_version(project, "", version_id)

    def save_prompt_version(self, project: dict, configuration_id: str, content: str, *, note: str = "", created_by: str = "local_user") -> tuple[dict, bool]:
        from backend.domain.prompts.service import save_prompt_version as domain_save_prompt_version
        return domain_save_prompt_version(project, configuration_id, content, note=note, created_by=created_by)

    def restore_prompt_version(self, project: dict, target_version_id: str, *, note: str = "", created_by: str = "local_user") -> tuple[dict, bool]:
        from backend.domain.prompts.service import restore_prompt_version as domain_restore_prompt_version
        return domain_restore_prompt_version(project, target_version_id, note=note, created_by=created_by)

    def diff_prompt_versions(self, v1_content: str, v2_content: str, v1_name: str = "Bản cũ", v2_name: str = "Bản mới") -> str:
        return self.extraction_service.diff_prompt_versions({}, "", v1_content, v2_content) if hasattr(self.extraction_service, "diff_prompt_versions") else ""

    def preview_extraction_request(self, project: dict, **kwargs: Any) -> PreparedExtractionRequestDTO:
        return self.extraction_service.preview_extraction_request(project, **kwargs)

    def extract_chunk(self, project: dict, document: dict, chunk_record: dict, **kwargs: Any) -> EngineOutput:
        return self.extraction_service.extract_chunk(project, document, chunk_record, **kwargs)

    def extract_chunks_parallel(self, project: dict, tasks: list[tuple[dict, dict]], **kwargs: Any) -> dict[str, Any]:
        return self.extraction_service.extract_chunks_parallel(
            project, tasks, chunk_extractor=self.extract_chunk, project_saver=self.save_project, **kwargs
        )

    # =========================================================================
    # 3. PHÂN HỆ SCHEMA INTELLIGENCE (backend/modules/schema_intelligence)
    # =========================================================================

    def list_embedding_models(self) -> list[dict]:
        return list_registered_models()

    def get_edc_plus_r_settings(self, project: dict) -> EDCPlusRSettingsDTO:
        return self.schema_service.get_edc_plus_r_settings(project)

    def update_edc_plus_r_settings(self, project: dict, settings_dict: dict) -> dict:
        dto = EDCPlusRSettingsDTO.from_dict(settings_dict)
        project["edc_plus_r_settings"] = dto.to_dict()
        return project["edc_plus_r_settings"]

    def save_prompt_settings(self, project: dict, prompt: str, relations: list[dict], entity_types: list[dict]) -> bool:
        from backend.domain.catalogs.core import save_prompt_settings as domain_save_prompt_settings
        return domain_save_prompt_settings(project, prompt, relations, entity_types)

    def extraction_prompt(self, project: dict) -> str:
        from backend.domain.catalogs.core import extraction_prompt as domain_extraction_prompt
        return domain_extraction_prompt(project)

    def retrieve_schema_for_chunk(self, project: dict, chunk_text: str) -> dict[str, list[dict]]:
        return self.schema_service.retrieve_schema_for_chunk(project, chunk_text)

    def rank_alignment_candidates(self, project: dict, kind: str, open_name: str, open_definition: str, top_k: int = 5) -> list[dict]:
        return self.schema_service.rank_alignment_candidates(project, kind, open_name, open_definition, top_k=top_k)

    def refresh_proposal_candidates(self, project: dict, proposal_ids: list[str], kind: str | None = None, *, save: bool = True, embedder: Any | None = None) -> dict[str, Any]:
        return self.schema_service.refresh_proposal_candidates(project, proposal_ids, kind=kind, save=save, embedder=embedder)

    def run_target_alignment_on_pending(self, project: dict, *, proposal_ids: list[str] | None = None, kind: str | None = None) -> dict:
        return self.schema_service.run_target_alignment_on_pending(project, proposal_ids=proposal_ids, kind=kind)

    def decide_proposal(self, project: dict, proposal_id: str, action: str, canonical_name: str = "", definition: str = "", note: str = "", description: str = "") -> dict:
        return self.schema_service.decide_proposal(project, proposal_id, action, canonical_name, definition, note, description)

    def decide_single_proposal(self, project: dict, proposal_id: str, action: str, canonical_name: str = "", definition: str = "", note: str = "", description: str = "") -> dict[str, Any]:
        return self.schema_service.decide_single_proposal(project, proposal_id, action, canonical_name, definition, note, description)

    def preview_proposal_decisions(self, project: dict, request: BulkReviewRequestDTO | dict) -> BulkReviewPreviewDTO:
        return self.schema_service.preview_proposal_decisions(project, request)

    def apply_proposal_decisions(self, project: dict, request: BulkReviewRequestDTO | dict, *, preview: BulkReviewPreviewDTO | dict | None = None) -> BulkReviewResultDTO:
        return self.schema_service.apply_proposal_decisions(project, request, preview=preview)

    # =========================================================================
    # 4. PHÂN HỆ CURATION (backend/modules/curation)
    # =========================================================================

    def preview_curation_decisions(self, project: dict, request: CurationReviewRequestDTO | dict) -> CurationPreviewDTO:
        return self.curation_service.preview_curation_decisions(project, request)

    def apply_curation_decisions(self, project: dict, request: CurationReviewRequestDTO | dict, *, preview: CurationPreviewDTO | dict | None = None) -> CurationResultDTO:
        return self.curation_service.apply_curation_decisions(project, request, preview=preview)

    def preview_entity_merge(self, project: dict, request: EntityMergeRequestDTO | dict) -> EntityMergePreviewDTO:
        return self.curation_service.preview_entity_merge(project, request)

    def apply_entity_merge(self, project: dict, request: EntityMergeRequestDTO | dict, *, preview: EntityMergePreviewDTO | dict | None = None) -> CurationResultDTO:
        return self.curation_service.apply_entity_merge(project, request, preview=preview)

    def apply_bulk_entity_merges(self, project: dict, pairs: list[Any], *, collapse_edges: bool = False, note: str = "", actor: str = "human_reviewer") -> CurationResultDTO:
        from backend.domain.curation.merge import apply_bulk_entity_merges as domain_bulk
        return self.curation_service._commit_curation_operation(
            project,
            expected_revision="",
            request_id="bulk_merge",
            request_hash="",
            executor=lambda p: domain_bulk(p, pairs, collapse_edges=collapse_edges, note=note, actor=actor, mutate_in_place=False),
        )

    def relation_duplicate_suggestions(
        self,
        project: dict,
        fuzzy_threshold: float = 0.75,
        *,
        threshold: float | None = None,
        include_dismissed: bool = False,
        **kwargs: Any,
    ) -> list[dict]:
        eff_threshold = threshold if threshold is not None else fuzzy_threshold
        return self.curation_service.relation_duplicate_suggestions(
            project,
            fuzzy_threshold=eff_threshold,
            include_dismissed=include_dismissed,
            **kwargs,
        )

    def apply_relation_merge(
        self,
        project: dict,
        source_relations: list[str] | str,
        target_relation: str,
        *,
        collapse_edges: bool = False,
        note: str = "",
        actor: str = "human_reviewer",
        **kwargs: Any,
    ) -> CurationResultDTO:
        return self.curation_service.apply_relation_merge(
            project,
            source_relations,
            target_relation,
            collapse_edges=collapse_edges,
            note=note,
            actor=actor,
            **kwargs,
        )

    def bulk_apply_relation_merges(self, project: dict, mappings: list[Any], *, collapse_edges: bool = False, note: str = "", actor: str = "human_reviewer") -> CurationResultDTO:
        return self.curation_service.bulk_apply_relation_merges(project, mappings, collapse_edges=collapse_edges, note=note, actor=actor)

    def collapse_duplicate_edges(self, project: dict, *, actor: str = "human_reviewer", note: str = "") -> CurationResultDTO:
        return self.curation_service.collapse_duplicate_edges(project, actor=actor, note=note)

    def mark_relation_pair_not_duplicate(self, project: dict, rel_a: str, rel_b: str, note: str = "") -> dict:
        return self.curation_service.mark_relation_pair_not_duplicate(project, rel_a, rel_b, note=note)

    def mark_relation_pairs_not_duplicate_bulk(self, project: dict, pairs: list[tuple[str, str]], *, kind: str = "relations", note: str = "") -> dict[str, Any]:
        return self.curation_service.mark_relation_pairs_not_duplicate_bulk(project, pairs, kind=kind, note=note)

    def mark_pair_not_duplicate(self, project: dict, node_a_id: str, node_b_id: str, *, note: str = "", actor: str = "human_reviewer", save: bool = True) -> dict[str, Any]:
        return self.curation_service.mark_pair_not_duplicate(project, node_a_id, node_b_id, note=note, actor=actor, save=save)

    def mark_pairs_not_duplicate_bulk(self, project: dict, pairs: list[Any], *, note: str = "", actor: str = "human_reviewer", save: bool = True) -> dict[str, Any]:
        return self.curation_service.mark_pairs_not_duplicate_bulk(project, pairs, note=note, actor=actor, save=save)

    def preview_clustering_prompt(self, project: dict, kind: str = "relations", custom_instructions: str = "", scope: str = "top_60") -> str:
        return self.curation_service.preview_clustering_prompt(project, kind=kind, custom_instructions=custom_instructions, scope=scope)

    def scan_semantic_clusters(self, project: dict, kind: str = "relations", **kwargs: Any) -> dict[str, Any]:
        return self.curation_service.scan_semantic_clusters(project, kind=kind, **kwargs)

    def apply_semantic_clusters(self, project: dict, kind: str, approved_clusters: list[dict], **kwargs: Any) -> CurationResultDTO:
        return self.curation_service.apply_semantic_clusters(project, kind, approved_clusters, **kwargs)

    def edit_edge_fact(self, project: dict, request: EdgeEditRequestDTO | dict) -> CurationResultDTO:
        return self.curation_service.edit_edge_fact(project, request)

    def edit_entity_profile(self, project: dict, request: EntityEditRequestDTO | dict) -> CurationResultDTO:
        return self.curation_service.edit_entity_profile(project, request)

    def select_evidence_span(self, project: dict, edge_id: str, start_char: int, end_char: int, **kwargs: Any) -> dict[str, Any]:
        return self.curation_service.select_evidence_span(project, edge_id, start_char, end_char, **kwargs)

    def inspect_edge_schema_status(self, project: dict, edge: dict) -> dict[str, Any]:
        return self.curation_service.inspect_edge_schema_status(project, edge)

    def validate_edge_for_approval(self, project: dict, edge: dict, **kwargs: Any) -> dict[str, Any]:
        return self.curation_service.validate_edge_for_approval(project, edge, **kwargs)

    def is_edge_exportable(self, project: dict, edge: dict) -> bool:
        return self.curation_service.is_edge_exportable(project, edge)

    def compute_apparent_duplicate_edge_groups(self, project: dict) -> list[dict[str, Any]]:
        return self.curation_service.compute_apparent_duplicate_edge_groups(project)

    def evidence_context(self, project: dict, edge: dict) -> dict:
        return self.curation_service.evidence_context(project, edge)

    def set_edge_status(self, project: dict, edge_id: str, status: str, **kwargs: Any) -> dict:
        return self.curation_service.set_edge_status(project, edge_id, status, **kwargs)

    def set_edges_status(self, project: dict, edge_ids: list[str], status: str) -> dict:
        return self.curation_service.set_edges_status(project, edge_ids, status)

    def approvable_edges(self, project: dict) -> list[str]:
        return self.curation_service.approvable_edges(project)

    def update_edge(self, project: dict, edge_id: str, **fields: Any) -> dict:
        return self.curation_service.update_edge(project, edge_id, **fields)

    def update_node(self, project: dict, node_id: str, **fields: Any) -> dict:
        return self.curation_service.update_node(project, node_id, **fields)

    def duplicate_suggestions(self, project: dict, fuzzy_threshold: float = 0.0) -> list[dict]:
        return self.curation_service.duplicate_suggestions(project, fuzzy_threshold)

    def merge_nodes(self, project: dict, keep: str, drop: str) -> dict:
        return self.curation_service.merge_nodes(project, keep, drop)

    def review_stats(self, project: dict, include_duplicates: bool = False) -> dict:
        return self.curation_service.review_stats(project, include_duplicates=include_duplicates)

    def token_totals(self, project: dict) -> dict:
        return self.curation_service.token_totals(project)

    # =========================================================================
    # 5. PHÂN HỆ GRAPH QA & EXPORT (backend/modules/graph_qa)
    # =========================================================================

    def validate_integrity(self, project: dict) -> list[str]:
        return self.graph_qa_service.validate_integrity(project)

    def approved_graph(self, project: dict) -> tuple[list[dict], list[dict]]:
        return self.graph_qa_service.approved_graph(project)

    def approved_json_bytes(self, project: dict) -> bytes:
        return self.graph_qa_service.approved_json_bytes(project)

    def csv_bytes(self, records: list[dict], headers: list[str], list_fields: tuple[str, ...] = ()) -> bytes:
        return self.graph_qa_service.csv_bytes(records, headers, list_fields)

    def export_zip(self, project: dict, *, qa_max_samples: int = 2000) -> bytes:
        return self.graph_qa_service.export_zip(project, qa_max_samples=qa_max_samples)

    def sync_neo4j(self, project: dict, uri: str, user: str, password: str, database: str = "neo4j", driver: Any = None) -> dict:
        return self.graph_qa_service.sync_neo4j(project, uri, user, password, database, driver=driver)

    def test_neo4j(self, uri: str, user: str, password: str, database: str = "neo4j", driver: Any = None) -> tuple[bool, str]:
        return self.graph_qa_service.test_neo4j(uri, user, password, database, driver=driver)

    def test_llm(self, provider: str, api_key: str, model: str, base_url: str = "", client: Any = None) -> tuple[bool, str]:
        effective_key = (api_key or "").strip() or get_api_key(provider)
        return LLMGateway.test_connection(provider, effective_key, model, base_url=base_url, client=client)

    def retrieve_subgraph(self, project: dict, query: str, **kwargs: Any) -> SubgraphRetrievalResult:
        return self.graph_qa_service.retrieve_subgraph(project, query, **kwargs)

    def answer_question_with_graph(self, subgraph_or_project: Any, query: str = "", **kwargs: Any) -> dict[str, Any]:
        return self.graph_qa_service.answer_question_with_graph(subgraph_or_project, query=query, **kwargs)

    def generate_qa_benchmark(self, project: dict, **kwargs: Any) -> list[dict[str, Any]]:
        return self.graph_qa_service.generate_qa_benchmark(project, **kwargs)

    def generate_training_qa_dataset(self, project: dict, **kwargs: Any) -> dict[str, Any]:
        return self.graph_qa_service.generate_training_qa_dataset(project, **kwargs)

    def paraphrase_qa_questions_with_llm(self, items: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        return self.graph_qa_service.paraphrase_qa_questions_with_llm(items, **kwargs)

    def evaluate_retrieval_methods(self, project: dict, **kwargs: Any) -> dict[str, Any]:
        return self.graph_qa_service.evaluate_retrieval_methods(project, **kwargs)

    def load_project_from_export_bytes(self, raw_bytes: bytes, filename: str = "") -> dict[str, Any]:
        return self.graph_qa_service.load_project_from_export_bytes(raw_bytes, filename=filename)

    # =========================================================================
    # 6. PHÂN HỆ TRAINING (backend/modules/training)
    # =========================================================================

    def export_training_datasets(self, project: dict) -> dict:
        return self.training_service.export_project(project)


_SINGLETON: KGStudioFacade | None = None


def get_facade() -> KGStudioFacade:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = KGStudioFacade()
    return _SINGLETON


def reset_facade(facade: KGStudioFacade | None = None) -> KGStudioFacade | None:
    global _SINGLETON
    prev = _SINGLETON
    _SINGLETON = facade
    return prev


__all__ = [
    "KGStudioFacade",
    "get_facade",
    "reset_facade",
    "compute_project_revision",
]
