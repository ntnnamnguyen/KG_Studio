"""Lớp Điều phối Trung tâm (Backend Facade) độc lập 100%."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading
from typing import Any

from backend.domain.catalogs.service import (
     catalog_rows,
    compute_catalog_hash,
    compute_full_request_hash,
    compute_project_revision,
    decide_proposal,
    extraction_prompt,
    preview_proposal_decisions as domain_preview_proposal_decisions,
    apply_proposal_decisions as domain_apply_proposal_decisions,
    prompt_signature,
    save_prompt_settings,
)
from backend.domain.curation.service import (
    apply_bulk_entity_merges as domain_apply_bulk_entity_merges,
    apply_curation_decisions as domain_apply_curation_decisions,
    apply_entity_merge as domain_apply_entity_merge,
    apply_relation_merge as domain_apply_relation_merge,
    approvable_edges,
    bulk_apply_relation_merges as domain_bulk_apply_relation_merges,
    compute_apparent_duplicate_edge_groups,
    compute_curation_request_hash,
    duplicate_suggestions,
    evidence_context,
    inspect_edge_schema_status,
    is_edge_exportable,
    mark_pair_not_duplicate as domain_mark_pair_not_duplicate,
    mark_relation_pair_not_duplicate as domain_mark_relation_pair_not_duplicate,
    merge_nodes,
    preview_curation_decisions as domain_preview_curation_decisions,
    preview_entity_merge as domain_preview_entity_merge,
    relation_duplicate_suggestions as domain_relation_duplicate_suggestions,
    review_stats,
    select_edge_evidence_span,
    set_edge_status,
    set_edges_status,
    token_totals,
    update_edge,
    update_node,
    validate_edge_for_approval,
)
from backend.domain.dataset_exporter.exporter import ActiveLearningExporter
from backend.domain.documents.processor import add_document, document_chunks
from backend.domain.extraction.base_engine import ChunkContext, EngineOutput
from backend.domain.extraction.registry import EngineRegistry, default_registry
from backend.domain.extraction.validator import cache_key
from backend.domain.graph.service import approved_graph, approved_json_bytes, csv_bytes, export_zip, validate_integrity
from backend.domain.schema_intelligence.aligner import TargetAligner
from backend.domain.schema_intelligence.retriever import SchemaRetriever
from backend.integrations.embedder_gateway import default_embedder, list_registered_models
from backend.integrations.llm_gateway import LLMGateway
from backend.integrations.neo4j_gateway import Neo4jGateway
from backend.repositories.json_repo import JsonProjectRepository
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from backend.domain.prompts.service import (
    DEFAULT_PROMPTS,
    compute_prompt_hash,
    diff_prompt_versions,
    get_active_prompt_content,
    get_active_prompt_version,
    get_prompt_version,
    list_prompt_versions,
    restore_prompt_version,
    save_prompt_version,
)
from shared.catalog_utils import edc_prompt, relation_catalog
from shared.constants import MODE_EDC, MODE_EDC_PLUS_R, MODE_FIXED
from shared.schemas.prompts import PreparedExtractionRequestDTO
from shared.secrets_manager import get_api_key
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
from shared.text_utils import now_iso, sha, uid


class KGStudioFacade:
    """Điểm kết nối duy nhất cho mọi tác vụ Backend (Dự án, Tài liệu, EDC+R, Kiểm duyệt, Xuất, ML Lab)."""

    def __init__(
        self,
        *,
        json_repo: JsonProjectRepository | None = None,
        sqlite_repo: SQLiteProjectRepository | None = None,
        vector_repo: VectorIndexRepository | None = None,
        engine_registry: EngineRegistry | None = None,
        exporter: ActiveLearningExporter | None = None,
    ) -> None:
        self.json_repo = json_repo or JsonProjectRepository()
        self.sqlite_repo = sqlite_repo or SQLiteProjectRepository()
        self.vector_repo = vector_repo or VectorIndexRepository()
        self.retriever = SchemaRetriever(vector_repo=self.vector_repo)
        self.aligner = TargetAligner(vector_repo=self.vector_repo)
        self.engine_registry = engine_registry or default_registry
        self.exporter = exporter or ActiveLearningExporter()
        self._locks_guard = threading.Lock()
        self._project_locks: dict[str, threading.RLock] = {}
        self._last_committed_revision: dict[str, str] = {}
        self._idempotency_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def _get_lock(self, project_key: str) -> threading.RLock:
        key = str(project_key or "default")
        with self._locks_guard:
            if key not in self._project_locks:
                self._project_locks[key] = threading.RLock()
            return self._project_locks[key]

    def _current_model_fingerprint(self, project: dict) -> str:
        try:
            settings = self.get_edc_plus_r_settings(project)
            embedder = default_embedder(settings.embedder_model)
            return getattr(embedder, "fingerprint", "") or ""
        except Exception:
            return ""

    def _sync_sqlite_safe(self, project: dict, result_dto: Any | None = None) -> tuple[str, str]:
        """Đồng bộ SQLite an toàn; nếu lỗi, đánh dấu sync_pending và ghi nhận lỗi vào project/result mà không làm hỏng commit JSON."""
        name = project.get("name", "")
        try:
            self.sqlite_repo.sync_from_project_dict(project)
            if name:
                self.json_repo.clear_sync_pending(name)
            project["sync_pending"] = False
            project["sync_error"] = ""
            if result_dto is not None:
                result_dto.sync_status = "synced"
                result_dto.sync_error = ""
            return "synced", ""
        except Exception as exc:
            err_str = str(exc)
            if name:
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
    ) -> None:
        """Kiểm tra xung đột đa phiên: nếu một phiên khác đã commit lên đĩa sau expected_revision."""
        if not expected_revision:
            return
        last_committed_rev = self._last_committed_revision.get(proj_id)
        mem_rev = compute_project_revision(project)
        if last_committed_rev and last_committed_rev != mem_rev and expected_revision != last_committed_rev:
            raise ValueError(
                "Dự án đã được cập nhật bởi một phiên làm việc khác (revision mismatch). Vui lòng tải lại và xem trước lại."
            )
        if proj_name and self.json_repo.project_exists(proj_name):
            try:
                disk_proj = self.json_repo.load_project(proj_name)
                disk_rev = compute_project_revision(disk_proj)
                if last_committed_rev and disk_rev == last_committed_rev and disk_rev != mem_rev:
                    raise ValueError(
                        "Dự án trên đĩa đã thay đổi bởi phiên khác kể từ lúc xem trước. Vui lòng xem trước lại."
                    )
            except ValueError:
                raise
            except Exception:
                pass

    # --- Quản lý Dự án ---
    def list_projects(self) -> list[str]:
        return self.json_repo.list_projects()

    def list_project_headers(self) -> list[dict]:
        """Trả về danh sách metadata tóm tắt của các dự án (không nạp toàn bộ JSON đồ thị)."""
        return self.json_repo.list_project_headers()

    def load_project(self, name: str) -> dict:
        project = self.json_repo.load_project(name)
        proj_id = str(project.get("project_id") or project.get("name") or name)
        self._last_committed_revision[proj_id] = compute_project_revision(project)
        self._sync_sqlite_safe(project)
        return project

    def save_project(self, project: dict) -> Path:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self._get_lock(proj_id):
            path = self.json_repo.save_project(project)
            self._last_committed_revision[proj_id] = compute_project_revision(project)
            try:
                self.vector_repo.invalidate_project_indices(
                    proj_id,
                    kind="relations",
                    current_catalog_items=catalog_rows(project, "relations"),
                )
                self.vector_repo.invalidate_project_indices(
                    proj_id,
                    kind="entity_types",
                    current_catalog_items=catalog_rows(project, "entity_types"),
                )
            except Exception:
                pass
            self._sync_sqlite_safe(project)
            return path

    def resync_sqlite(self, project: dict) -> dict[str, Any]:
        """Đồng bộ lại SQLite cho dự án đang có trạng thái sync_pending."""
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self._get_lock(proj_id):
            self.sqlite_repo.sync_from_project_dict(project)
            self.json_repo.clear_sync_pending(project["name"])
            project["sync_pending"] = False
            project["sync_error"] = ""
            return {"status": "synced", "sync_pending": False, "project_id": proj_id}

    def create_snapshot(self, project: dict) -> Path:
        return self.json_repo.create_snapshot(project)

    def list_snapshots(self, project: dict) -> list[Path]:
        return self.json_repo.list_snapshots(project)

    def restore_snapshot(self, project: dict, path: Path) -> dict:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self._get_lock(proj_id):
            restored = self.json_repo.restore_snapshot(project, path)
            self._last_committed_revision[proj_id] = compute_project_revision(restored)
            try:
                self.vector_repo.invalidate_project_indices(
                    proj_id,
                    kind="relations",
                    current_catalog_items=catalog_rows(restored, "relations"),
                )
                self.vector_repo.invalidate_project_indices(
                    proj_id,
                    kind="entity_types",
                    current_catalog_items=catalog_rows(restored, "entity_types"),
                )
            except Exception:
                pass
            self._sync_sqlite_safe(restored)
            project.clear()
            project.update(restored)
            return project

    def project_revision(self, project: dict) -> str:
        return compute_project_revision(project)

    # --- Quản lý Tài liệu ---
    def add_document(self, project: dict, name: str, data: bytes, place_scope: str = "", source_label: str = "") -> tuple[bool, str]:
        return add_document(project, name, data, place_scope, source_label)

    def document_chunks(self, doc: dict, limit: int = 3200, overlap: int = 250) -> list[dict]:
        return document_chunks(doc, limit, overlap)

    # --- Quản lý Danh mục & Cấu hình EDC+R ---
    def list_embedding_models(self) -> list[dict]:
        return list_registered_models()

    def available_extraction_modes(self) -> list[dict]:
        return self.engine_registry.available_modes()

    def get_edc_plus_r_settings(self, project: dict) -> EDCPlusRSettingsDTO:
        return EDCPlusRSettingsDTO.from_dict(project.get("edc_plus_r_settings"))

    def update_edc_plus_r_settings(self, project: dict, settings_dict: dict) -> dict:
        dto = EDCPlusRSettingsDTO.from_dict(settings_dict)
        project["edc_plus_r_settings"] = dto.to_dict()
        return project["edc_plus_r_settings"]

    def save_prompt_settings(self, project: dict, prompt: str, relations: list[dict], entity_types: list[dict]) -> bool:
        return save_prompt_settings(project, prompt, relations, entity_types)

    def extraction_prompt(self, project: dict) -> str:
        return extraction_prompt(project)

    # --- Quản lý Phiên bản Prompt & Xem trước Request ---
    def get_active_prompt_version(self, project: dict, configuration_id: str | None = None) -> dict | None:
        return get_active_prompt_version(project, configuration_id)

    def get_active_prompt_content(self, project: dict, configuration_id: str | None = None) -> str:
        return get_active_prompt_content(project, configuration_id)

    def list_prompt_versions(self, project: dict, configuration_id: str | None = None) -> list[dict]:
        return list_prompt_versions(project, configuration_id)

    def get_prompt_version(self, project: dict, version_id: str) -> dict | None:
        return get_prompt_version(project, version_id)

    def save_prompt_version(
        self,
        project: dict,
        configuration_id: str,
        content: str,
        *,
        note: str = "",
        created_by: str = "local_user",
    ) -> tuple[dict, bool]:
        return save_prompt_version(project, configuration_id, content, note=note, created_by=created_by)

    def restore_prompt_version(
        self,
        project: dict,
        target_version_id: str,
        *,
        note: str = "",
        created_by: str = "local_user",
    ) -> tuple[dict, bool]:
        return restore_prompt_version(project, target_version_id, note=note, created_by=created_by)

    def diff_prompt_versions(
        self,
        v1_content: str,
        v2_content: str,
        v1_name: str = "Bản cũ",
        v2_name: str = "Bản mới",
    ) -> str:
        return diff_prompt_versions(v1_content, v2_content, v1_name=v1_name, v2_name=v2_name)

    def preview_extraction_request(
        self,
        project: dict,
        *,
        configuration_id: str,
        doc_id: str = "",
        chunk_number: int = 1,
        draft_content: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 16000,
    ) -> PreparedExtractionRequestDTO:
        docs = project.get("documents", [])
        target_doc = None
        if doc_id:
            for d in docs:
                if d.get("id") == doc_id or d.get("name") == doc_id:
                    target_doc = d
                    break
        if not target_doc and docs:
            target_doc = docs[0]

        if target_doc:
            chunks = self.document_chunks(target_doc)
            chunk_rec = next((c for c in chunks if c.get("chunk_number") == chunk_number), chunks[0] if chunks else None)
            chunk_text = chunk_rec.get("text", "") if chunk_rec else (target_doc.get("text", "")[:2000])
        else:
            chunk_text = "Văn bản mẫu để kiểm tra trước cấu hình trích xuất và kiểm tra ngân sách token."

        cfg_id = configuration_id or project.get("extraction_mode", MODE_FIXED)
        active_ver = get_active_prompt_version(project, cfg_id)

        if draft_content is not None and draft_content.strip():
            base_instructions = draft_content.strip()
            is_draft = True
            ver_id = active_ver.get("id", "draft") if active_ver else "draft"
            ver_hash = compute_prompt_hash(base_instructions)
        else:
            is_draft = False
            base_instructions = active_ver.get("content", DEFAULT_PROMPTS.get(cfg_id, "")) if active_ver else DEFAULT_PROMPTS.get(cfg_id, "")
            ver_id = active_ver.get("id", "") if active_ver else ""
            ver_hash = active_ver.get("content_hash", "") if active_ver else ""

        retrieval_summary: dict[str, Any] = {}
        if cfg_id == MODE_FIXED:
            catalogs = {"relations": relation_catalog(project), "entity_types": project.get("entity_types", [])}
            appended = (
                "\n\nDANH MỤC QUAN HỆ VÀ LOẠI THỰC THỂ ĐƯỢC PHÉP (JSON):\n"
                + json.dumps(catalogs, ensure_ascii=False, indent=2)
                + "\nChỉ dùng name trong relations cho trường quan_he và name trong entity_types cho trường loai."
            )
            full_sys_prompt = base_instructions + appended
            allowed_relations = project.get("relations", [])
            open_mode = False
        elif cfg_id == MODE_EDC:
            appended = "Hợp đồng JSON cấu trúc trích xuất mở (EDC_SCHEMA)."
            full_sys_prompt = edc_prompt(base_instructions)
            allowed_relations = []
            open_mode = True
        elif cfg_id == MODE_EDC_PLUS_R:
            settings = self.get_edc_plus_r_settings(project)
            embedder = default_embedder(settings.embedder_model)
            retrieved = self.retriever.retrieve_for_chunk(
                project,
                chunk_text,
                top_k_relations=settings.top_k_relations,
                top_k_entity_types=settings.top_k_entity_types,
                embedder=embedder,
            )
            schema_block = self.retriever.format_retrieved_schema_block(retrieved)
            augmented = base_instructions.strip() + "\n\n" + schema_block
            full_sys_prompt = edc_prompt(augmented)
            appended = schema_block
            allowed_relations = []
            open_mode = True
            retrieval_summary = {
                "retrieved_relations": len(retrieved.get("relations", [])),
                "retrieved_entity_types": len(retrieved.get("entity_types", [])),
                "embedder_model": embedder.model_id,
            }
        else:
            full_sys_prompt = base_instructions
            appended = ""
            allowed_relations = []
            open_mode = False

        prov = provider or LLMGateway.DEFAULT_PROVIDER
        mod = model or LLMGateway.DEFAULT_MODELS.get(prov, "deepseek-chat")

        return LLMGateway.prepare_extraction_request(
            provider=prov,
            model=mod,
            system_prompt=full_sys_prompt,
            chunk=chunk_text,
            allowed_relations=allowed_relations,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            open_mode=open_mode,
            project_id=str(project.get("project_id", "")),
            configuration_id=cfg_id,
            prompt_version_id=ver_id,
            prompt_content_hash=ver_hash,
            base_instructions=base_instructions,
            appended_content=appended,
            loop_index=1,
            is_draft=is_draft,
            retrieval_summary=retrieval_summary,
        )

    # --- Schema Retriever (+R) & Target Alignment ---
    def retrieve_schema_for_chunk(self, project: dict, chunk_text: str) -> dict[str, list[dict]]:
        settings = self.get_edc_plus_r_settings(project)
        embedder = default_embedder(settings.embedder_model)
        return self.retriever.retrieve_for_chunk(
            project,
            chunk_text,
            top_k_relations=settings.top_k_relations,
            top_k_entity_types=settings.top_k_entity_types,
            embedder=embedder,
        )

    def rank_alignment_candidates(self, project: dict, kind: str, open_name: str, open_definition: str, top_k: int = 5) -> list[dict]:
        settings = self.get_edc_plus_r_settings(project)
        embedder = default_embedder(settings.embedder_model)
        cands = self.aligner.rank_candidates(
            project,
            kind,
            open_name,
            open_definition,
            top_k=top_k,
            embedder=embedder,
        )
        return [c.to_dict() for c in cands]

    def refresh_proposal_candidates(
        self,
        project: dict,
        proposal_ids: list[str],
        kind: str | None = None,
        *,
        save: bool = True,
        embedder: Any | None = None,
    ) -> dict[str, Any]:
        """Làm mới gợi ý Target Alignment chỉ trên danh sách proposal_ids được chọn."""
        settings = self.get_edc_plus_r_settings(project)
        active_embedder = embedder if embedder is not None else default_embedder(settings.embedder_model)
        summary = self.aligner.refresh_candidates_for_proposals(
            project,
            proposal_ids=proposal_ids,
            kind=kind,
            candidate_threshold=settings.candidate_threshold,
            top_k=5,
            embedder=active_embedder,
        )
        if save and self.json_repo.project_exists(project.get("name", "")):
            self.save_project(project)
        return summary

    def run_target_alignment_on_pending(
        self,
        project: dict,
        *,
        proposal_ids: list[str] | None = None,
        kind: str | None = None,
    ) -> dict:
        settings = self.get_edc_plus_r_settings(project)
        embedder = default_embedder(settings.embedder_model)
        return self.aligner.align_project_proposals(
            project,
            auto_align_threshold=settings.auto_align_threshold,
            candidate_threshold=settings.candidate_threshold,
            enable_llm_verifier=False,
            embedder=embedder,
            proposal_ids=proposal_ids,
            kind=kind,
        )

    def decide_proposal(
        self,
        project: dict,
        proposal_id: str,
        action: str,
        canonical_name: str = "",
        definition: str = "",
        note: str = "",
        description: str = "",
    ) -> dict:
        return decide_proposal(project, proposal_id, action, canonical_name, definition, note, description)

    # --- Duyệt EDC Hàng Loạt (Preview & Commit Transactional) ---
    def preview_proposal_decisions(
        self,
        project: dict,
        request: BulkReviewRequestDTO | dict,
    ) -> BulkReviewPreviewDTO:
        """Xem trước lô quyết định EDC (không ghi đĩa, không tạo snapshot, không đổi trạng thái)."""
        model_fp = self._current_model_fingerprint(project)
        preview = domain_preview_proposal_decisions(
            project,
            request,
            current_model_fingerprint=model_fp,
        )
        return preview

    def apply_proposal_decisions(
        self,
        project: dict,
        request: BulkReviewRequestDTO | dict,
        *,
        preview: BulkReviewPreviewDTO | dict | None = None,
    ) -> BulkReviewResultDTO:
        """Xác thực lại lô quyết định dưới khóa dự án, tạo snapshot, lưu bundle JSON và đồng bộ SQLite."""
        req = BulkReviewRequestDTO.from_dict(request)
        proj_id = str(project.get("project_id") or req.project_id or project.get("name") or "default")
        proj_name = str(project.get("name") or "")

        with self._get_lock(proj_id):
            # 1. Kiểm tra idempotency theo request_id (chống nhấn đúp / retry lặp)
            full_hash = compute_full_request_hash(req)
            if req.request_id:
                cached = self._idempotency_cache.get((proj_id, req.request_id))
                if cached is None:
                    cached = project.get("edc_idempotency_store", {}).get(req.request_id)
                if cached is None and proj_name and self.json_repo.project_exists(proj_name):
                    try:
                        disk_p = self.json_repo.load_project(proj_name)
                        cached = disk_p.get("edc_idempotency_store", {}).get(req.request_id)
                    except Exception:
                        cached = None
                if cached is not None:
                    if cached.get("request_hash") != full_hash:
                        raise ValueError(
                            f"request_id '{req.request_id}' đã được dùng cho một nội dung request khác. Từ chối thực thi."
                        )
                    replayed = BulkReviewResultDTO.from_dict(copy.deepcopy(cached["result"]))
                    replayed.idempotent_replay = True
                    return replayed

            # 2. Kiểm tra xung đột đa phiên (nếu một phiên khác đã commit lên đĩa sau expected_revision)
            self._check_revision_conflict(proj_id, proj_name, project, req.expected_revision)

            # 3. Xác thực lại toàn bộ lô trên bản sao dự án
            model_fp = self._current_model_fingerprint(project)
            prev_cat_hash = compute_catalog_hash(project, req.kind if req.kind in ("relations", "entity_types") else None)
            candidate, result = domain_apply_proposal_decisions(
                project,
                req,
                preview=preview,
                current_model_fingerprint=model_fp,
                mutate_in_place=False,
            )

            # 4. Tạo đúng 1 snapshot trước khi commit bộ file
            snap_path = self.json_repo.create_snapshot(project)
            snap_str = str(snap_path)
            result.snapshot_path = snap_str
            if candidate.get("schema_decision_batches"):
                candidate["schema_decision_batches"][-1]["snapshot_path"] = snap_str

            # 5. Lưu thông tin idempotency vào candidate trước khi ghi bundle JSON
            idem_entry = {
                "request_id": result.request_id,
                "request_hash": full_hash,
                "at": now_iso(),
                "result": result.to_dict(),
            }
            candidate.setdefault("edc_idempotency_store", {})[result.request_id] = idem_entry

            # 6. Lưu atomic bundle (project.json + relations.json + entity_types.json); lỗi I/O sẽ rollback
            try:
                self.json_repo.save_project(candidate)
            except Exception:
                snap_path.unlink(missing_ok=True)
                raise

            # 7. Chỉ cập nhật trạng thái dự án trong bộ nhớ sau khi JSON đã commit thành công
            project.clear()
            project.update(candidate)
            self._last_committed_revision[proj_id] = result.revision_after

            # 8. Vô hiệu hóa chỉ mục vector nếu danh mục thay đổi (không làm đảo quyết định nếu lỗi)
            new_cat_hash = compute_catalog_hash(project, req.kind if req.kind in ("relations", "entity_types") else None)
            if new_cat_hash != prev_cat_hash:
                result.vector_index_status = "invalidated"
                try:
                    self.vector_repo.invalidate_project_indices(
                        proj_id,
                        kind=req.kind,
                        current_catalog_items=catalog_rows(project, req.kind),
                    )
                except Exception:
                    pass
            else:
                result.vector_index_status = "valid"

            # 9. Đồng bộ SQLite trong transaction; nếu lỗi thì đánh dấu sync_pending nhưng vẫn giữ kết quả committed
            self._sync_sqlite_safe(project, result)

            idem_entry["result"] = result.to_dict()
            project.setdefault("edc_idempotency_store", {})[result.request_id] = idem_entry
            self._idempotency_cache[(proj_id, result.request_id)] = idem_entry
            return result

    # --- Trích xuất ---
    def extract_chunk(
        self,
        project: dict,
        document: dict,
        chunk_record: dict,
        *,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 12000,
        client: object | None = None,
    ) -> EngineOutput:
        mode = project.get("extraction_mode", "closed")
        engine = self.engine_registry.get(mode)
        ctx = ChunkContext(
            project=project,
            document=document,
            chunk_record=chunk_record,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            client=client,
        )
        output = engine.process_chunk(ctx)

        sys_prompt = extraction_prompt(project)
        rel_sig = (
            "edc_plus_r"
            if mode == MODE_EDC_PLUS_R
            else ("edc" if mode == MODE_EDC else "|".join(project.get("relations", [])))
        )
        p_id = prompt_signature(sys_prompt, [rel_sig])
        c_key = cache_key(document, chunk_record, p_id, rel_sig, provider, model, base_url, temperature, max_tokens)

        raw = output.raw_response or ""
        project.setdefault("runs", []).append(
            {
                "at": now_iso(),
                "doc_id": document["id"],
                "doc_name": document.get("name", ""),
                "chunk_number": chunk_record["chunk_number"],
                "chunk_hash": chunk_record.get("chunk_hash", ""),
                "cache_key": c_key,
                "provider": provider,
                "model": model,
                "prompt_id": p_id,
                "prompt_version_id": getattr(output, "prompt_version_id", ""),
                "prompt_content_hash": getattr(output, "prompt_content_hash", ""),
                "prepared_request_hash": getattr(output, "prepared_request_hash", ""),
                "prepared_request": getattr(output, "prepared_request", {}),
                "extraction_mode": mode,
                "input_tokens": output.input_tokens,
                "output_tokens": output.output_tokens,
                "added_nodes": output.ingest_stats.get("added_nodes", 0),
                "added_edges": output.ingest_stats.get("added_edges", 0),
                "duplicates": output.ingest_stats.get("duplicates", 0),
                "discarded": output.ingest_stats.get("discarded", 0),
                "evidence_mismatch": output.ingest_stats.get("evidence_mismatch", 0),
                "disallowed_relations": output.ingest_stats.get("disallowed_relations", []),
                "rejected_items": output.ingest_stats.get("rejected_items", []),
                "new_proposals": output.ingest_stats.get("new_proposals", 0),
                "warnings": output.warnings,
                "step_traces": output.step_traces,
                "alignment_summary": output.alignment_summary,
                "raw_response": raw[:100_000],
                "raw_truncated": len(raw) > 100_000,
                "status": "ok",
            }
        )
        project.setdefault("processed_chunks", {})[c_key] = now_iso()
        return output

    # --- Kiểm duyệt & Gộp thực thể ---
    def _commit_curation_operation(
        self,
        project: dict,
        *,
        expected_revision: str,
        request_id: str,
        request_hash: str,
        executor,
    ) -> CurationResultDTO:
        """Thực thi transactional cho mọi thao tác ghi ở Trang 5 (kiểm tra idempotency, revision, tạo snapshot, ghi atomic JSON, đồng bộ SQLite)."""
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        proj_name = str(project.get("name") or "")

        with self._get_lock(proj_id):
            if request_id:
                cache_key_id = (f"curation:{proj_id}", request_id)
                cached = self._idempotency_cache.get(cache_key_id)
                if cached is None:
                    cached = project.get("curation_idempotency_store", {}).get(request_id)
                if cached is None and proj_name and self.json_repo.project_exists(proj_name):
                    try:
                        disk_p = self.json_repo.load_project(proj_name)
                        cached = disk_p.get("curation_idempotency_store", {}).get(request_id)
                    except Exception:
                        cached = None
                if cached is not None:
                    if cached.get("request_hash") != request_hash:
                        raise ValueError(
                            f"request_id '{request_id}' đã được dùng cho một nội dung thao tác khác. Từ chối thực thi."
                        )
                    replayed = CurationResultDTO.from_dict(copy.deepcopy(cached["result"]))
                    replayed.idempotent_replay = True
                    return replayed

            self._check_revision_conflict(proj_id, proj_name, project, expected_revision)

            candidate, result = executor(project)

            snap_path = self.json_repo.create_snapshot(project)
            snap_str = str(snap_path)
            result.snapshot_path = snap_str
            if candidate.get("curation_decision_batches"):
                candidate["curation_decision_batches"][-1]["snapshot_path"] = snap_str
            if candidate.get("entity_merges") and result.operation == "entity_merge":
                candidate["entity_merges"][-1]["snapshot_path"] = snap_str

            idem_entry = {
                "request_id": result.request_id,
                "request_hash": request_hash,
                "at": now_iso(),
                "result": result.to_dict(),
            }
            candidate.setdefault("curation_idempotency_store", {})[result.request_id] = idem_entry

            try:
                self.json_repo.save_project(candidate)
            except Exception:
                snap_path.unlink(missing_ok=True)
                raise

            project.clear()
            project.update(candidate)
            self._last_committed_revision[proj_id] = result.revision_after

            self._sync_sqlite_safe(project, result)

            idem_entry["result"] = result.to_dict()
            project.setdefault("curation_idempotency_store", {})[result.request_id] = idem_entry
            self._idempotency_cache[(f"curation:{proj_id}", result.request_id)] = idem_entry
            return result

    def preview_curation_decisions(
        self,
        project: dict,
        request: CurationReviewRequestDTO | dict,
    ) -> CurationPreviewDTO:
        return domain_preview_curation_decisions(project, request)

    def apply_curation_decisions(
        self,
        project: dict,
        request: CurationReviewRequestDTO | dict,
        *,
        preview: CurationPreviewDTO | dict | None = None,
    ) -> CurationResultDTO:
        req = CurationReviewRequestDTO.from_dict(request)
        req_hash = compute_curation_request_hash(req)

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_apply_curation_decisions(proj, req, preview=preview, mutate_in_place=False)

        return self._commit_curation_operation(
            project,
            expected_revision=req.expected_revision,
            request_id=req.request_id,
            request_hash=req_hash,
            executor=_exec,
        )

    def preview_entity_merge(
        self,
        project: dict,
        request: EntityMergeRequestDTO | dict,
    ) -> EntityMergePreviewDTO:
        return domain_preview_entity_merge(project, request)

    def apply_entity_merge(
        self,
        project: dict,
        request: EntityMergeRequestDTO | dict,
        *,
        preview: EntityMergePreviewDTO | dict | None = None,
    ) -> CurationResultDTO:
        req = EntityMergeRequestDTO.from_dict(request)
        req_hash = compute_curation_request_hash(req)

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_apply_entity_merge(proj, req, preview=preview, mutate_in_place=False)

        return self._commit_curation_operation(
            project,
            expected_revision=req.expected_revision,
            request_id=req.request_id,
            request_hash=req_hash,
            executor=_exec,
        )

    def apply_bulk_entity_merges(
        self,
        project: dict,
        pairs: list[dict | tuple[str, str]],
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        req_hash = sha(json.dumps(pairs, sort_keys=True, default=str))[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_apply_bulk_entity_merges(proj, pairs, note=note, actor=actor)

        return self._commit_curation_operation(
            project,
            expected_revision="",
            request_id=uid(),
            request_hash=req_hash,
            executor=_exec,
        )

    def relation_duplicate_suggestions(
        self,
        project: dict,
        fuzzy_threshold: float = 0.75,
        *,
        include_dismissed: bool = False,
    ) -> list[dict[str, Any]]:
        return domain_relation_duplicate_suggestions(
            project,
            fuzzy_threshold=fuzzy_threshold,
            include_dismissed=include_dismissed,
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
        req_hash = sha(json.dumps({"src": sorted(source_relations), "tgt": target_relation}, sort_keys=True))[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_apply_relation_merge(proj, source_relations, target_relation, note=note, actor=actor)

        return self._commit_curation_operation(
            project,
            expected_revision="",
            request_id=uid(),
            request_hash=req_hash,
            executor=_exec,
        )

    def bulk_apply_relation_merges(
        self,
        project: dict,
        mappings: list[dict | tuple[str, str]],
        *,
        note: str = "",
        actor: str = "human_reviewer",
    ) -> CurationResultDTO:
        req_hash = sha(json.dumps(mappings, sort_keys=True, default=str))[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_bulk_apply_relation_merges(proj, mappings, note=note, actor=actor)

        return self._commit_curation_operation(
            project,
            expected_revision="",
            request_id=uid(),
            request_hash=req_hash,
            executor=_exec,
        )

    def mark_relation_pair_not_duplicate(
        self,
        project: dict,
        rel_a: str,
        rel_b: str,
        note: str = "",
    ) -> dict:
        res = domain_mark_relation_pair_not_duplicate(project, rel_a, rel_b, note=note)
        self.json_repo.save_project(project)
        return res

    def edit_edge_fact(
        self,
        project: dict,
        request: EdgeEditRequestDTO | dict,
    ) -> CurationResultDTO:
        req = EdgeEditRequestDTO.from_dict(request)
        req_hash = compute_curation_request_hash(req)

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            rev_before = compute_project_revision(proj)
            if req.expected_revision and req.expected_revision != rev_before:
                raise ValueError(
                    f"Phiên bản dự án đã thay đổi ({req.expected_revision} != {rev_before}). Vui lòng tải lại trước khi sửa cạnh."
                )
            candidate = copy.deepcopy(proj)
            kwargs: dict[str, Any] = {"note": req.note, "actor": req.actor}
            for fld in ("source", "target", "relation", "evidence", "doc_id"):
                val = getattr(req, fld)
                if val is not None:
                    kwargs[fld] = val
            if req.start_char is not None or req.end_char is not None:
                kwargs["start_char"] = req.start_char
                kwargs["end_char"] = req.end_char
            updated = update_edge(candidate, req.edge_id, **kwargs)
            rev_after = compute_project_revision(candidate)
            batch_id = uid()
            request_id = req.request_id or uid()
            candidate.setdefault("curation_decision_batches", []).append(
                {
                    "batch_id": batch_id,
                    "request_id": request_id,
                    "request_hash": req_hash,
                    "at": now_iso(),
                    "actor": req.actor,
                    "operation": "edit_edge",
                    "applied_ids": [req.edge_id],
                    "revision_before": rev_before,
                    "revision_after": rev_after,
                    "snapshot_path": "",
                }
            )
            res = CurationResultDTO(
                batch_id=batch_id,
                request_id=request_id,
                project_id=str(candidate.get("project_id") or req.project_id),
                operation="edit_edge",
                status="committed",
                apply_mode="all_or_nothing",
                revision_before=rev_before,
                revision_after=rev_after,
                applied_ids=[req.edge_id],
                skipped_ids=[],
                applied_count=1,
                skipped_count=0,
                item_results=[{"edge_id": req.edge_id, "status_after": updated.get("status", "")}],
                affected_edge_ids=[req.edge_id],
            )
            return candidate, res

        return self._commit_curation_operation(
            project,
            expected_revision=req.expected_revision,
            request_id=req.request_id,
            request_hash=req_hash,
            executor=_exec,
        )

    def edit_entity_profile(
        self,
        project: dict,
        request: EntityEditRequestDTO | dict,
    ) -> CurationResultDTO:
        req = EntityEditRequestDTO.from_dict(request)
        req_hash = compute_curation_request_hash(req)

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            rev_before = compute_project_revision(proj)
            if req.expected_revision and req.expected_revision != rev_before:
                raise ValueError(
                    f"Phiên bản dự án đã thay đổi ({req.expected_revision} != {rev_before}). Vui lòng tải lại trước khi sửa thực thể."
                )
            candidate = copy.deepcopy(proj)
            kwargs: dict[str, Any] = {"note": req.note, "actor": req.actor}
            for fld in ("name", "kind", "description", "aliases"):
                val = getattr(req, fld)
                if val is not None:
                    kwargs[fld] = val
            updated = update_node(candidate, req.node_id, **kwargs)
            last_hist = candidate.get("curation_history", [])[-1] if candidate.get("curation_history") else {}
            inv_edges = list(last_hist.get("affected_edge_ids") or last_hist.get("invalidated_edge_ids") or [])
            rev_after = compute_project_revision(candidate)
            batch_id = uid()
            request_id = req.request_id or uid()
            candidate.setdefault("curation_decision_batches", []).append(
                {
                    "batch_id": batch_id,
                    "request_id": request_id,
                    "request_hash": req_hash,
                    "at": now_iso(),
                    "actor": req.actor,
                    "operation": "edit_entity",
                    "applied_ids": [req.node_id],
                    "invalidated_edge_ids": inv_edges,
                    "revision_before": rev_before,
                    "revision_after": rev_after,
                    "snapshot_path": "",
                }
            )
            res = CurationResultDTO(
                batch_id=batch_id,
                request_id=request_id,
                project_id=str(candidate.get("project_id") or req.project_id),
                operation="edit_entity",
                status="committed",
                apply_mode="all_or_nothing",
                revision_before=rev_before,
                revision_after=rev_after,
                applied_ids=[req.node_id],
                skipped_ids=[],
                applied_count=1,
                skipped_count=0,
                item_results=[{"node_id": req.node_id, "kind": updated.get("kind", ""), "invalidated_edge_ids": inv_edges}],
                affected_edge_ids=inv_edges,
            )
            return candidate, res

        return self._commit_curation_operation(
            project,
            expected_revision=req.expected_revision,
            request_id=req.request_id,
            request_hash=req_hash,
            executor=_exec,
        )

    def select_evidence_span(
        self,
        project: dict,
        edge_id: str,
        start_char: int,
        end_char: int,
        *,
        actor: str = "human_reviewer",
        save: bool = True,
    ) -> dict[str, Any]:
        ctx = select_edge_evidence_span(project, edge_id, start_char, end_char, actor=actor)
        if save and self.json_repo.project_exists(project.get("name", "")):
            self.save_project(project)
        return ctx

    def mark_pair_not_duplicate(
        self,
        project: dict,
        node_a_id: str,
        node_b_id: str,
        *,
        note: str = "",
        actor: str = "human_reviewer",
        save: bool = True,
    ) -> dict[str, Any]:
        res = domain_mark_pair_not_duplicate(project, node_a_id, node_b_id, note=note, actor=actor)
        if save and self.json_repo.project_exists(project.get("name", "")):
            self.save_project(project)
        return res

    def inspect_edge_schema_status(self, project: dict, edge: dict) -> dict[str, Any]:
        return inspect_edge_schema_status(project, edge)

    def validate_edge_for_approval(self, project: dict, edge: dict, **kwargs) -> dict[str, Any]:
        return validate_edge_for_approval(project, edge, **kwargs)

    def is_edge_exportable(self, project: dict, edge: dict) -> bool:
        return is_edge_exportable(project, edge)

    def compute_apparent_duplicate_edge_groups(self, project: dict) -> list[dict[str, Any]]:
        return compute_apparent_duplicate_edge_groups(project)

    def evidence_context(self, project: dict, edge: dict) -> dict:
        return evidence_context(project, edge)

    def set_edge_status(
        self,
        project: dict,
        edge_id: str,
        status: str,
        override_reason: str = "",
        reviewer: str = "",
        *,
        reason_code: str = "",
        self_loop_confirmed: bool = False,
    ) -> dict:
        return set_edge_status(
            project,
            edge_id,
            status,
            override_reason,
            reviewer,
            reason_code=reason_code,
            self_loop_confirmed=self_loop_confirmed,
        )

    def set_edges_status(self, project: dict, edge_ids: list[str], status: str) -> dict:
        return set_edges_status(project, edge_ids, status)

    def approvable_edges(self, project: dict) -> list[str]:
        return approvable_edges(project)

    def update_edge(self, project: dict, edge_id: str, **fields) -> dict:
        return update_edge(project, edge_id, **fields)

    def update_node(self, project: dict, node_id: str, **fields) -> dict:
        return update_node(project, node_id, **fields)

    def duplicate_suggestions(self, project: dict, fuzzy_threshold: float = 0.0) -> list[dict]:
        return duplicate_suggestions(project, fuzzy_threshold)

    def merge_nodes(self, project: dict, keep: str, drop: str) -> dict:
        return merge_nodes(project, keep, drop)

    def review_stats(self, project: dict, include_duplicates: bool = False) -> dict:
        return review_stats(project, include_duplicates=include_duplicates)

    def token_totals(self, project: dict) -> dict:
        return token_totals(project)

    # --- Đồ thị & Xuất ---
    def validate_integrity(self, project: dict) -> list[str]:
        return validate_integrity(project)

    def approved_graph(self, project: dict) -> tuple[list[dict], list[dict]]:
        return approved_graph(project)

    def approved_json_bytes(self, project: dict) -> bytes:
        return approved_json_bytes(project)

    def csv_bytes(self, records: list[dict], headers: list[str], list_fields: tuple[str, ...] = ()) -> bytes:
        return csv_bytes(records, headers, list_fields)

    def export_zip(self, project: dict) -> bytes:
        return export_zip(project)

    def sync_neo4j(self, project: dict, uri: str, user: str, password: str, database: str = "neo4j", driver=None) -> dict:
        return Neo4jGateway.sync_project(project, uri, user, password, database, driver=driver)

    def test_neo4j(self, uri: str, user: str, password: str, database: str = "neo4j", driver=None) -> tuple[bool, str]:
        return Neo4jGateway.test_connection(uri, user, password, database, driver=driver)

    def test_llm(self, provider: str, api_key: str, model: str, base_url: str = "", client=None) -> tuple[bool, str]:
        effective_key = (api_key or "").strip() or get_api_key(provider)
        return LLMGateway.test_connection(provider, effective_key, model, base_url=base_url, client=client)

    # --- Active Learning Exporter ---
    def export_training_datasets(self, project: dict) -> dict:
        return self.exporter.export_project(project)


_SINGLETON: KGStudioFacade | None = None


def get_facade() -> KGStudioFacade:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = KGStudioFacade()
    return _SINGLETON
