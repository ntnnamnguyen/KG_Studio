"""Application Service cho phân hệ Schema Intelligence (EDC, Catalogs, Target Alignment)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from backend.domain.catalogs.core import (
    catalog_rows,
    compute_catalog_hash,
    compute_decisions_hash,
    compute_full_request_hash,
    compute_project_revision,
    extraction_prompt,
    prompt_signature,
    save_prompt_settings,
)
from backend.domain.catalogs.proposals import (
    batch_proposal_impacts,
    is_proposal_candidates_stale,
    prepare_edc,
    proposal_impact,
    propose_term,
    schema_review_issue,
)
from backend.domain.catalogs.review import (
    apply_proposal_decisions as domain_apply_proposal_decisions,
    decide_proposal as domain_decide_proposal,
    preview_proposal_decisions as domain_preview_proposal_decisions,
)
from backend.domain.schema_intelligence.aligner import TargetAligner
from backend.domain.schema_intelligence.retriever import SchemaRetriever
from backend.integrations.embedder_gateway import default_embedder
from backend.modules.projects.public import ProjectCommitCoordinator
from shared.schemas.edc import (
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
)
from shared.schemas.project import EDCPlusRSettingsDTO
from shared.text_utils import sha, uid


class SchemaIntelligenceApplicationService:
    """Dịch vụ ứng dụng quản lý Danh mục Schema, Đề xuất EDC, và Target Alignment."""

    def __init__(
        self,
        *,
        commit_coordinator: ProjectCommitCoordinator | None = None,
        vector_repo: Any | None = None,
        retriever: SchemaRetriever | None = None,
        aligner: TargetAligner | None = None,
    ) -> None:
        self.commit_coordinator = commit_coordinator
        self.vector_repo = vector_repo
        self.retriever = retriever or SchemaRetriever(vector_repo=self.vector_repo)
        self.aligner = aligner or TargetAligner(vector_repo=self.vector_repo)

    def _current_model_fingerprint(self, project: dict) -> str:
        try:
            raw_s = project.get("edc_plus_r_settings") or {}
            embedder_model = raw_s.get("embedder_model", "hybrid_vn:default") if isinstance(raw_s, dict) else "hybrid_vn:default"
            embedder = default_embedder(embedder_model)
            return getattr(embedder, "fingerprint", "") or ""
        except Exception:
            return ""

    def get_edc_plus_r_settings(self, project: dict) -> EDCPlusRSettingsDTO:
        raw = project.get("edc_plus_r_settings") or {}
        if isinstance(raw, EDCPlusRSettingsDTO):
            return raw
        return EDCPlusRSettingsDTO.from_dict(raw if isinstance(raw, dict) else {})

    # --- Catalog CRUD & Hashes ---

    def catalog_rows(self, project: dict, kind: str) -> list[dict]:
        return catalog_rows(project, kind)

    def compute_catalog_hash(self, project: dict, kind: str) -> str:
        return compute_catalog_hash(project, kind)

    def prepare_edc(self, project: dict, clean: dict, payload: dict, context: dict) -> None:
        prepare_edc(project, clean, payload, context)

    def propose_term(
        self,
        project: dict,
        kind: str,
        name: str,
        definition: str = "",
        observation: dict | None = None,
        *,
        source_chunk_id: str = "",
        doc_id: str = "",
    ) -> tuple[str, str]:
        obs = dict(observation or {})
        if source_chunk_id and "chunk_id" not in obs:
            obs["chunk_id"] = source_chunk_id
        if doc_id and "doc_id" not in obs:
            obs["doc_id"] = doc_id
        return propose_term(
            project,
            kind=kind,
            name=name,
            definition=definition,
            observation=obs,
        )

    # --- EDC Review (Preview & Apply Transactional) ---

    def preview_proposal_decisions(
        self,
        project: dict,
        request: BulkReviewRequestDTO | dict,
        current_model_fingerprint: str | None = None,
    ) -> BulkReviewPreviewDTO:
        fp = current_model_fingerprint if current_model_fingerprint is not None else self._current_model_fingerprint(project)
        return domain_preview_proposal_decisions(
            project,
            request,
            current_model_fingerprint=fp,
        )

    def apply_proposal_decisions(
        self,
        project: dict,
        request: BulkReviewRequestDTO | dict,
        *,
        preview: BulkReviewPreviewDTO | dict | None = None,
        current_model_fingerprint: str | None = None,
    ) -> BulkReviewResultDTO:
        req = BulkReviewRequestDTO.from_dict(request)
        full_hash = compute_full_request_hash(req)
        fp = current_model_fingerprint if current_model_fingerprint is not None else self._current_model_fingerprint(project)

        def _exec(proj: dict) -> tuple[dict, BulkReviewResultDTO]:
            return domain_apply_proposal_decisions(
                proj,
                req,
                preview=preview,
                current_model_fingerprint=fp,
                mutate_in_place=False,
            )

        def _on_snapshot(candidate: dict, result: BulkReviewResultDTO, snap_str: str) -> None:
            if candidate.get("schema_decision_batches"):
                candidate["schema_decision_batches"][-1]["snapshot_path"] = snap_str

        if self.commit_coordinator is not None:
            return self.commit_coordinator.commit(
                project,
                request_id=req.request_id,
                request_hash=full_hash,
                expected_revision=req.expected_revision,
                executor=_exec,
                idempotency_store_key="edc_idempotency_store",
                result_dto_cls=BulkReviewResultDTO,
                on_snapshot_created=_on_snapshot,
                vector_invalidation_kind=req.kind if req.kind in ("relations", "entity_types") else None,
            )
        raise RuntimeError(
            "Thao tác áp dụng quyết định lược đồ có lưu trữ yêu cầu ProjectCommitCoordinator; "
            "không cho phép mutate bộ nhớ khi thiếu coordinator."
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
    ) -> dict[str, Any]:
        return domain_decide_proposal(
            project,
            proposal_id,
            action,
            canonical_name,
            definition,
            note,
            description,
        )

    def decide_single_proposal(
        self,
        project: dict,
        proposal_id: str,
        action: str,
        canonical_name: str = "",
        definition: str = "",
        note: str = "",
        description: str = "",
        *,
        expected_revision: str = "",
    ) -> dict[str, Any]:
        """Quyết định một đề xuất đơn lẻ có tạo snapshot và bảo đảm commit transactional."""
        if self.commit_coordinator is None:
            raise RuntimeError(
                "Thao tác quyết định đề xuất có lưu trữ yêu cầu ProjectCommitCoordinator; "
                "không cho phép mutate bộ nhớ khi thiếu coordinator."
            )
        captured_impact: dict[str, Any] = {}

        def _exec(proj: dict) -> tuple[dict, dict[str, Any]]:
            nonlocal captured_impact
            candidate, captured_impact = domain_decide_proposal(
                proj,
                proposal_id,
                action,
                canonical_name=canonical_name,
                definition=definition,
                note=note,
                description=description,
                mutate_in_place=False,
            )
            return candidate, captured_impact

        req_id = f"single_prop_{proposal_id}_{uid()[:8]}"
        req_hash = sha(
            json.dumps(
                {
                    "proposal_id": proposal_id,
                    "action": action,
                    "canonical_name": canonical_name,
                    "definition": definition,
                    "note": note,
                    "description": description,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )[:16]
        rev = expected_revision or str(project.get("project_revision", ""))
        self.commit_coordinator.commit(
            project,
            request_id=req_id,
            request_hash=req_hash,
            expected_revision=rev,
            executor=_exec,
            idempotency_store_key="edc_idempotency_store",
            vector_invalidation_kind=("relations", "entity_types"),
        )
        return captured_impact

    # --- Target Alignment & Retrieval ---

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

    def rank_alignment_candidates(
        self,
        project: dict,
        kind: str,
        open_name: str,
        open_definition: str,
        top_k: int = 5,
    ) -> list[dict]:
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
        if save and self.commit_coordinator is not None and self.commit_coordinator.project_store.project_exists(project.get("name", "")):
            self.commit_coordinator.save_metadata_in_lock(project)
        return summary

    def run_target_alignment_on_pending(
        self,
        project: dict,
        *,
        proposal_ids: list[str] | None = None,
        kind: str | None = None,
        enable_llm_verifier: bool | None = None,
        llm_params: dict | None = None,
        save: bool = True,
    ) -> dict:
        settings = self.get_edc_plus_r_settings(project)
        embedder = default_embedder(settings.embedder_model)
        use_verifier = (
            settings.enable_llm_verifier if enable_llm_verifier is None else bool(enable_llm_verifier)
        ) and bool(llm_params)
        align_kwargs = {
            "auto_align_threshold": settings.auto_align_threshold,
            "candidate_threshold": settings.candidate_threshold,
            "enable_llm_verifier": use_verifier,
            "llm_params": llm_params,
            "embedder": embedder,
            "proposal_ids": proposal_ids,
            "kind": kind,
        }
        if (
            save
            and self.commit_coordinator is not None
            and project.get("name")
            and self.commit_coordinator.project_store.project_exists(project.get("name", ""))
        ):
            req_id = f"auto_align_{uid()[:8]}"
            req_hash = sha(
                json.dumps(
                    {
                        "proposal_ids": sorted(proposal_ids or []),
                        "kind": kind or "",
                        "use_verifier": use_verifier,
                        "auto_align_threshold": settings.auto_align_threshold,
                        "candidate_threshold": settings.candidate_threshold,
                        "embedder_model": settings.embedder_model,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )[:16]

            def _exec(proj: dict) -> tuple[dict, dict[str, Any]]:
                candidate = copy.deepcopy(proj)
                summary = self.aligner.align_project_proposals(candidate, **align_kwargs)
                return candidate, summary

            return self.commit_coordinator.commit(
                project,
                request_id=req_id,
                request_hash=req_hash,
                executor=_exec,
                idempotency_store_key="edc_idempotency_store",
                vector_invalidation_kind=None,
            )

        return self.aligner.align_project_proposals(project, **align_kwargs)
