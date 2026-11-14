"""Application Service cho phân hệ Curation, Evidence & Entity/Relation Merging."""
from __future__ import annotations

import copy
import json
from typing import Any, Callable

from backend.domain.catalogs.core import compute_project_revision
from backend.domain.curation.service import (
    apply_bulk_entity_merges as domain_apply_bulk_entity_merges,
    apply_curation_decisions as domain_apply_curation_decisions,
    apply_entity_merge as domain_apply_entity_merge,
    apply_relation_merge as domain_apply_relation_merge,
    apply_semantic_clusters as domain_apply_semantic_clusters,
    approvable_edges,
    bulk_apply_relation_merges as domain_bulk_apply_relation_merges,
    clear_gazetteer as domain_clear_gazetteer,
    collapse_duplicate_edges as domain_collapse_duplicate_edges,
    compute_apparent_duplicate_edge_groups,
    compute_curation_request_hash,
    delete_gazetteer_entry as domain_delete_gazetteer_entry,
    duplicate_suggestions,
    evidence_context,
    expand_grouped_gazetteer_rows as domain_expand_grouped_gazetteer_rows,
    gazetteer_to_csv_bytes as domain_gazetteer_to_csv_bytes,
    gazetteer_to_json_bytes as domain_gazetteer_to_json_bytes,
    inspect_edge_schema_status,
    is_edge_exportable,
    list_gazetteer_entries as domain_list_gazetteer_entries,
    list_grouped_gazetteer_entries as domain_list_grouped_gazetteer_entries,
    mark_pair_not_duplicate as domain_mark_pair_not_duplicate,
    mark_pairs_not_duplicate_bulk as domain_mark_pairs_not_duplicate_bulk,
    mark_relation_pair_not_duplicate as domain_mark_relation_pair_not_duplicate,
    mark_relation_pairs_not_duplicate_bulk as domain_mark_relation_pairs_not_duplicate_bulk,
    merge_gazetteer_entries as domain_merge_gazetteer_entries,
    merge_nodes,
    parse_gazetteer_bytes as domain_parse_gazetteer_bytes,
    preload_gazetteer_template as domain_preload_gazetteer_template,
    preview_clustering_prompt as domain_preview_clustering_prompt,
    preview_curation_decisions as domain_preview_curation_decisions,
    preview_entity_merge as domain_preview_entity_merge,
    relation_duplicate_suggestions as domain_relation_duplicate_suggestions,
    replace_gazetteer_entries as domain_replace_gazetteer_entries,
    review_stats,
    scan_semantic_clusters as domain_scan_semantic_clusters,
    select_edge_evidence_span,
    set_edge_status,
    set_edges_status,
    token_totals,
    update_edge,
    update_node,
    upsert_gazetteer_entry as domain_upsert_gazetteer_entry,
    validate_edge_for_approval,
)
from shared.schemas.curation import (
    CurationPreviewDTO,
    CurationResultDTO,
    CurationReviewRequestDTO,
    EdgeEditRequestDTO,
    EntityEditRequestDTO,
    EntityMergePreviewDTO,
    EntityMergeRequestDTO,
)
from shared.text_utils import now_iso, sha, uid


class CurationApplicationService:
    """Dịch vụ ứng dụng quản lý Duyệt cạnh, Chỉnh sửa sự thật, Gộp thực thể/quan hệ, và Gom cụm ngữ nghĩa."""

    def __init__(
        self,
        *,
        commit_coordinator: Any | None = None,
        project_store: Any | None = None,
    ) -> None:
        self.commit_coordinator = commit_coordinator
        self.project_store = project_store

    def _commit_curation_operation(
        self,
        project: dict,
        *,
        expected_revision: str,
        request_id: str,
        request_hash: str,
        executor: Callable[[dict], tuple[dict, CurationResultDTO]],
    ) -> CurationResultDTO:
        def _on_snapshot(candidate: dict, result: CurationResultDTO, snap_str: str) -> None:
            if candidate.get("curation_decision_batches"):
                candidate["curation_decision_batches"][-1]["snapshot_path"] = snap_str
            if candidate.get("entity_merges") and getattr(result, "operation", "") in ("entity_merge", "bulk_entity_merge"):
                candidate["entity_merges"][-1]["snapshot_path"] = snap_str
            if candidate.get("relation_merges") and getattr(result, "operation", "") in ("relation_merge", "bulk_relation_merge", "collapse_duplicate_edges"):
                candidate["relation_merges"][-1]["snapshot_path"] = snap_str
            if candidate.get("entity_type_merges") and getattr(result, "operation", "") in ("bulk_entity_type_merge", "entity_type_merge"):
                candidate["entity_type_merges"][-1]["snapshot_path"] = snap_str

        if self.commit_coordinator is not None:
            return self.commit_coordinator.commit(
                project,
                request_id=request_id,
                request_hash=request_hash,
                expected_revision=expected_revision,
                executor=executor,
                idempotency_store_key="curation_idempotency_store",
                result_dto_cls=CurationResultDTO,
                on_snapshot_created=_on_snapshot,
            )
        raise RuntimeError(
            "Thao tác kiểm duyệt có lưu trữ (persistent curation command) yêu cầu ProjectCommitCoordinator; "
            "không cho phép fallback ghi trực tiếp hoặc mutate thiếu coordinator. Dùng preview_* cho mô phỏng thuần túy."
        )

    # --- Curation Review Operations ---

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
            return domain_apply_curation_decisions(
                proj,
                req,
                preview=preview,
                mutate_in_place=False,
            )

        return self._commit_curation_operation(
            project,
            expected_revision=req.expected_revision,
            request_id=req.request_id,
            request_hash=req_hash,
            executor=_exec,
        )

    # --- Entity Merge Operations ---

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
            return domain_apply_entity_merge(
                proj,
                req,
                preview=preview,
                mutate_in_place=False,
            )

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
        pairs: list[Any],
        *,
        collapse_edges: bool = False,
        note: str = "",
        actor: str = "human_reviewer",
        expected_revision: str = "",
        request_id: str = "",
    ) -> CurationResultDTO:
        normalized_inputs = [p.to_dict() if hasattr(p, "to_dict") else p for p in (pairs or [])]
        req_hash = sha(
            json.dumps(
                {
                    "pairs": normalized_inputs,
                    "collapse_edges": bool(collapse_edges),
                    "note": str(note or ""),
                    "actor": str(actor or ""),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_apply_bulk_entity_merges(
                proj,
                normalized_inputs,
                collapse_edges=collapse_edges,
                actor=actor,
                note=note,
                mutate_in_place=False,
            )

        return self._commit_curation_operation(
            project,
            expected_revision=expected_revision,
            request_id=request_id or uid(),
            request_hash=req_hash,
            executor=_exec,
        )

    # --- Relation Merge Operations ---

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
        return domain_relation_duplicate_suggestions(
            project,
            fuzzy_threshold=eff_threshold,
            include_dismissed=include_dismissed,
        )

    def apply_relation_merge(
        self,
        project: dict,
        source_relations: list[str] | str,
        target_relation: str,
        *,
        collapse_edges: bool = False,
        actor: str = "human_reviewer",
        note: str = "",
        **kwargs: Any,
    ) -> CurationResultDTO:
        srcs = [source_relations] if isinstance(source_relations, str) else list(source_relations)
        req_hash = sha(f"relation_merge::{srcs}::{target_relation}::{collapse_edges}")[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_apply_relation_merge(
                proj,
                srcs,
                target_relation,
                collapse_edges=collapse_edges,
                actor=actor,
                note=note,
                mutate_in_place=False,
            )

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
        mappings: list[dict | tuple[str, str]] | dict[str, str],
        *,
        collapse_edges: bool = False,
        actor: str = "human_reviewer",
        note: str = "",
    ) -> CurationResultDTO:
        req_hash = sha(f"bulk_relation_merge::{len(mappings)}::{collapse_edges}")[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_bulk_apply_relation_merges(
                proj,
                mappings,
                collapse_edges=collapse_edges,
                actor=actor,
                note=note,
                mutate_in_place=False,
            )

        return self._commit_curation_operation(
            project,
            expected_revision="",
            request_id=uid(),
            request_hash=req_hash,
            executor=_exec,
        )

    def collapse_duplicate_edges(
        self,
        project: dict,
        *,
        actor: str = "human_reviewer",
        note: str = "",
    ) -> CurationResultDTO:
        req_hash = sha(f"collapse_duplicate_edges::{project.get('name', '')}")[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            rev_before = compute_project_revision(proj)
            candidate, dropped_count, records = domain_collapse_duplicate_edges(
                proj,
                actor=actor,
                note=note,
                mutate_in_place=False,
            )
            rev_after = compute_project_revision(candidate)
            res = CurationResultDTO(
                batch_id=uid(),
                request_id=uid(),
                project_id=str(candidate.get("project_id") or candidate.get("name") or ""),
                operation="collapse_duplicate_edges",
                status="applied",
                apply_mode="all_or_nothing",
                revision_before=rev_before,
                revision_after=rev_after,
                applied_count=dropped_count,
                merged_duplicate_edges=dropped_count,
                item_results=records,
            )
            return candidate, res

        return self._commit_curation_operation(
            project,
            expected_revision="",
            request_id=uid(),
            request_hash=req_hash,
            executor=_exec,
        )

    def _commit_with_domain_return(
        self,
        project: dict,
        *,
        operation: str,
        request_hash: str,
        expected_revision: str = "",
        clone_keys: tuple[str, ...] = ("not_duplicate_pairs", "not_duplicate_relation_pairs", "curation_history"),
        fn: Callable[[dict], Any],
    ) -> Any:
        if self.commit_coordinator is None:
            raise RuntimeError(
                "Thao tác kiểm duyệt có lưu trữ (persistent curation command) yêu cầu ProjectCommitCoordinator; "
                "không cho phép fallback ghi trực tiếp hoặc mutate thiếu coordinator."
            )
        captured: list[Any] = []

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            candidate = dict(proj)
            for key in clone_keys:
                if isinstance(proj.get(key), list):
                    candidate[key] = copy.deepcopy(proj[key])
            captured.append(fn(candidate))
            res = CurationResultDTO(
                status="committed",
                operation=operation,
                revision_after=compute_project_revision(candidate),
            )
            return candidate, res

        self._commit_curation_operation(
            project,
            expected_revision=expected_revision,
            request_id=f"{operation}_{uid()[:10]}",
            request_hash=request_hash,
            executor=_exec,
        )
        return captured[0]

    def mark_relation_pair_not_duplicate(
        self,
        project: dict,
        rel_a: str,
        rel_b: str,
        note: str = "",
        *,
        save: bool = True,
        expected_revision: str = "",
    ) -> dict:
        if not save:
            return domain_mark_relation_pair_not_duplicate(project, rel_a, rel_b, note=note)
        req_hash = sha(f"mark_rel_not_dup::{rel_a}::{rel_b}::{note}")[:16]
        return self._commit_with_domain_return(
            project,
            operation="mark_relation_pair_not_duplicate",
            request_hash=req_hash,
            expected_revision=expected_revision,
            clone_keys=("not_duplicate_relation_pairs", "curation_history"),
            fn=lambda c: domain_mark_relation_pair_not_duplicate(c, rel_a, rel_b, note=note),
        )

    def mark_relation_pairs_not_duplicate_bulk(
        self,
        project: dict,
        pairs: list[tuple[str, str]],
        *,
        kind: str = "relations",
        note: str = "",
        save: bool = True,
        expected_revision: str = "",
    ) -> dict[str, Any]:
        if not save:
            return domain_mark_relation_pairs_not_duplicate_bulk(project, pairs, note=note)
        req_hash = sha(json.dumps({"op": "mark_rel_bulk", "pairs": [list(p) for p in pairs], "note": note}, ensure_ascii=False))[:16]
        return self._commit_with_domain_return(
            project,
            operation="mark_relation_pairs_not_duplicate_bulk",
            request_hash=req_hash,
            expected_revision=expected_revision,
            clone_keys=("not_duplicate_relation_pairs", "curation_history"),
            fn=lambda c: domain_mark_relation_pairs_not_duplicate_bulk(c, pairs, note=note),
        )

    def mark_pair_not_duplicate(
        self,
        project: dict,
        node_a_id: str,
        node_b_id: str,
        *,
        note: str = "",
        actor: str = "human_reviewer",
        save: bool = True,
        expected_revision: str = "",
    ) -> dict:
        if not save:
            return domain_mark_pair_not_duplicate(project, node_a_id, node_b_id, note=note, actor=actor)
        req_hash = sha(f"mark_pair_not_dup::{node_a_id}::{node_b_id}::{note}::{actor}")[:16]
        return self._commit_with_domain_return(
            project,
            operation="mark_pair_not_duplicate",
            request_hash=req_hash,
            expected_revision=expected_revision,
            clone_keys=("not_duplicate_pairs", "curation_history"),
            fn=lambda c: domain_mark_pair_not_duplicate(c, node_a_id, node_b_id, note=note, actor=actor),
        )

    def mark_pairs_not_duplicate_bulk(
        self,
        project: dict,
        pairs: list[tuple[str, str] | list[str] | dict[str, Any]],
        *,
        note: str = "",
        actor: str = "human_reviewer",
        save: bool = True,
        expected_revision: str = "",
    ) -> list[dict[str, Any]]:
        if not save:
            return domain_mark_pairs_not_duplicate_bulk(project, pairs, note=note, actor=actor)
        req_hash = sha(json.dumps({"op": "mark_pairs_bulk", "count": len(pairs), "note": note, "actor": actor}, ensure_ascii=False))[:16]
        return self._commit_with_domain_return(
            project,
            operation="mark_pairs_not_duplicate_bulk",
            request_hash=req_hash,
            expected_revision=expected_revision,
            clone_keys=("not_duplicate_pairs", "curation_history"),
            fn=lambda c: domain_mark_pairs_not_duplicate_bulk(c, pairs, note=note, actor=actor),
        )

    # --- Semantic Clustering ---

    def preview_clustering_prompt(
        self,
        project: dict,
        kind: str = "relations",
        custom_instructions: str = "",
        scope: str = "top_60",
    ) -> str:
        return domain_preview_clustering_prompt(
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
        return domain_scan_semantic_clusters(
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
        req_hash = sha(
            json.dumps(
                {"kind": kind, "clusters": approved_clusters, "collapse": collapse_duplicate_edges},
                sort_keys=True,
                default=str,
            )
        )[:16]

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            return domain_apply_semantic_clusters(
                proj,
                kind=kind,
                approved_clusters=approved_clusters,
                collapse_duplicate_edges=collapse_duplicate_edges,
                note=note,
                actor=actor,
                mutate_in_place=False,
            )

        return self._commit_curation_operation(
            project,
            expected_revision="",
            request_id=uid(),
            request_hash=req_hash,
            executor=_exec,
        )

    # --- Fact & Profile Editing ---

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
            updated = update_edge(candidate, req.edge_id, req=req)
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
            updated = update_node(candidate, req.node_id, req=req)
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
        expected_revision: str = "",
    ) -> dict[str, Any]:
        if not save:
            return select_edge_evidence_span(project, edge_id, start_char, end_char, actor=actor)
        req_hash = sha(f"select_span::{edge_id}::{start_char}::{end_char}::{actor}")[:16]
        return self._commit_with_domain_return(
            project,
            operation="select_evidence_span",
            request_hash=req_hash,
            expected_revision=expected_revision,
            clone_keys=("edges", "curation_history"),
            fn=lambda c: select_edge_evidence_span(c, edge_id, start_char, end_char, actor=actor),
        )

    # --- Pure Curation Queries & Inspection ---

    def inspect_edge_schema_status(self, project: dict, edge: dict) -> dict[str, Any]:
        return inspect_edge_schema_status(project, edge)

    def validate_edge_for_approval(self, project: dict, edge: dict, **kwargs: Any) -> dict[str, Any]:
        return validate_edge_for_approval(project, edge, **kwargs)

    def is_edge_exportable(self, project: dict, edge: dict) -> bool:
        return is_edge_exportable(project, edge)

    def compute_apparent_duplicate_edge_groups(self, project: dict) -> list[dict[str, Any]]:
        return compute_apparent_duplicate_edge_groups(project.get("edges", []))

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

    def update_edge(self, project: dict, edge_id: str, **fields: Any) -> dict:
        return update_edge(project, edge_id, **fields)

    def update_node(self, project: dict, node_id: str, **fields: Any) -> dict:
        return update_node(project, node_id, **fields)

    def duplicate_suggestions(self, project: dict, fuzzy_threshold: float = 0.0) -> list[dict]:
        return duplicate_suggestions(project, fuzzy_threshold)

    def merge_nodes(self, project: dict, keep: str, drop: str) -> dict:
        return merge_nodes(project, keep, drop)

    def review_stats(self, project: dict, include_duplicates: bool = False) -> dict:
        return review_stats(project, include_duplicates=include_duplicates)

    def token_totals(self, project: dict) -> dict:
        return token_totals(project)

    # --- Project Gazetteer & Continuous Curation ---

    def list_gazetteer_entries(self, project: dict) -> list[dict[str, Any]]:
        """Lấy danh sách các mục từ điển bí danh đã học của dự án."""
        return domain_list_gazetteer_entries(project)

    def list_grouped_gazetteer_entries(self, project: dict) -> list[dict[str, Any]]:
        """Lấy danh sách từ điển bí danh gom nhóm theo thực thể chuẩn."""
        return domain_list_grouped_gazetteer_entries(project)

    def expand_grouped_gazetteer_rows(
        self,
        grouped_rows: list[dict[str, Any]],
        *,
        strict_conflicts: bool = True,
    ) -> list[dict[str, str]]:
        """Bung phẳng bảng từ điển gom nhóm (aliases ngăn cách ';' hoặc '|') thành bản ghi 1-1."""
        return domain_expand_grouped_gazetteer_rows(grouped_rows, strict_conflicts=strict_conflicts)

    def parse_gazetteer_bytes(self, raw_bytes: bytes, filename: str = "") -> list[dict[str, str]]:
        """Phân tích tệp JSON hoặc CSV từ điển bí danh tải lên."""
        return domain_parse_gazetteer_bytes(raw_bytes, filename=filename)

    def gazetteer_to_json_bytes(self, project: dict) -> bytes:
        """Xuất từ điển bí danh dự án ra tệp JSON UTF-8."""
        return domain_gazetteer_to_json_bytes(project)

    def gazetteer_to_csv_bytes(self, project: dict, *, grouped: bool = True) -> bytes:
        """Xuất từ điển bí danh dự án ra tệp CSV (UTF-8 BOM cho Excel)."""
        return domain_gazetteer_to_csv_bytes(project, grouped=grouped)

    def _commit_gazetteer_mutation(
        self,
        project: dict,
        *,
        operation: str,
        request_id: str,
        request_hash: str,
        expected_revision: str,
        actor: str,
        audit_target: str,
        mutator: Callable[[dict], dict[str, Any]],
    ) -> CurationResultDTO:
        """Điều phối mutation từ điển trên bản sao an toàn, ghi audit trail và commit qua coordinator."""
        req_id = request_id or uid()

        def _exec(proj: dict) -> tuple[dict, CurationResultDTO]:
            rev_before = compute_project_revision(proj)
            candidate = copy.deepcopy(proj)
            meta = mutator(candidate)
            rev_after = compute_project_revision(candidate)
            applied_count = int(meta.get("applied_count", 0))
            skipped_count = int(meta.get("skipped_count", 0))
            status = str(meta.get("status") or ("applied" if applied_count > 0 or rev_after != rev_before else "skipped"))
            item_results = list(meta.get("item_results") or [])

            candidate.setdefault("curation_history", []).append(
                {
                    "id": uid(),
                    "at": now_iso(),
                    "actor": actor or "user",
                    "decision_origin": "human",
                    "action": operation,
                    "target_id": audit_target,
                    "note": str(meta.get("note") or ""),
                    "before": None,
                    "after": meta.get("after"),
                }
            )

            res = CurationResultDTO(
                batch_id=req_id,
                request_id=req_id,
                project_id=str(candidate.get("project_id") or candidate.get("name") or ""),
                operation=operation,
                status=status,
                revision_before=rev_before,
                revision_after=rev_after,
                applied_count=applied_count,
                skipped_count=skipped_count,
                item_results=item_results,
            )
            return candidate, res

        return self._commit_curation_operation(
            project,
            expected_revision=expected_revision,
            request_id=req_id,
            request_hash=request_hash,
            executor=_exec,
        )

    def upsert_gazetteer_entry(
        self,
        project: dict,
        alias: str,
        canonical_name: str,
        kind: str = "",
        *,
        source: str = "manual",
        expected_revision: str = "",
        request_id: str = "",
        actor: str = "",
    ) -> CurationResultDTO:
        """Thêm hoặc cập nhật một mục trong từ điển bí danh dự án qua Commit Coordinator."""
        alias_clean = alias.strip()
        canon_clean = canonical_name.strip()
        req_hash = sha(f"upsert_gazetteer::{alias_clean}::{canon_clean}::{kind}")[:16]

        def _mutate(cand: dict) -> dict[str, Any]:
            entry = domain_upsert_gazetteer_entry(
                cand,
                alias=alias_clean,
                canonical_name=canon_clean,
                kind=kind,
                source=source,
                actor=actor,
            )
            return {"applied_count": 1, "item_results": [entry], "after": entry}

        return self._commit_gazetteer_mutation(
            project,
            operation="upsert_gazetteer_entry",
            request_id=request_id,
            request_hash=req_hash,
            expected_revision=expected_revision,
            actor=actor,
            audit_target=alias_clean,
            mutator=_mutate,
        )

    def delete_gazetteer_entry(
        self,
        project: dict,
        alias: str,
        *,
        expected_revision: str = "",
        request_id: str = "",
        actor: str = "",
    ) -> CurationResultDTO:
        """Xóa một mục khỏi từ điển bí danh dự án qua Commit Coordinator (van an toàn khi gộp nhầm)."""
        alias_clean = alias.strip()
        req_hash = sha(f"delete_gazetteer::{alias_clean}")[:16]

        def _mutate(cand: dict) -> dict[str, Any]:
            deleted = domain_delete_gazetteer_entry(cand, alias=alias_clean, actor=actor)
            return {
                "applied_count": 1 if deleted else 0,
                "skipped_count": 0 if deleted else 1,
                "status": "applied" if deleted else "skipped",
            }

        return self._commit_gazetteer_mutation(
            project,
            operation="delete_gazetteer_entry",
            request_id=request_id,
            request_hash=req_hash,
            expected_revision=expected_revision,
            actor=actor,
            audit_target=alias_clean,
            mutator=_mutate,
        )

    def replace_gazetteer_entries(
        self,
        project: dict,
        entries: dict[str, Any] | list[dict[str, Any]],
        *,
        source: str = "manual_editor",
        expected_revision: str = "",
        request_id: str = "",
        actor: str = "",
    ) -> CurationResultDTO:
        """Thay thế toàn bộ từ điển bí danh dự án từ bảng biên tập hoặc file JSON/CSV tải lên."""
        req_hash = sha(f"replace_gazetteer::{json.dumps(entries, ensure_ascii=False, sort_keys=True, default=str)}")[:16]

        def _mutate(cand: dict) -> dict[str, Any]:
            count = domain_replace_gazetteer_entries(
                cand,
                entries=entries,
                source=source,
                actor=actor,
            )
            return {"applied_count": count, "status": "applied", "note": f"total={count}"}

        return self._commit_gazetteer_mutation(
            project,
            operation="replace_gazetteer_entries",
            request_id=request_id,
            request_hash=req_hash,
            expected_revision=expected_revision,
            actor=actor,
            audit_target="domain_gazetteer",
            mutator=_mutate,
        )

    def merge_gazetteer_entries(
        self,
        project: dict,
        entries: dict[str, Any] | list[dict[str, Any]],
        *,
        source: str = "imported_file",
        overwrite_existing: bool = False,
        expected_revision: str = "",
        request_id: str = "",
        actor: str = "",
    ) -> CurationResultDTO:
        """Gộp thêm các mục mới vào từ điển bí danh dự án qua Commit Coordinator."""
        req_hash = sha(
            f"merge_gazetteer::{overwrite_existing}::{json.dumps(entries, ensure_ascii=False, sort_keys=True, default=str)}"
        )[:16]

        def _mutate(cand: dict) -> dict[str, Any]:
            summary = domain_merge_gazetteer_entries(
                cand,
                entries=entries,
                source=source,
                actor=actor,
                overwrite_existing=overwrite_existing,
            )
            return {
                "applied_count": summary["added"] + summary["updated"],
                "skipped_count": summary["skipped"],
                "status": "applied",
                "item_results": [summary],
                "after": summary,
            }

        return self._commit_gazetteer_mutation(
            project,
            operation="merge_gazetteer_entries",
            request_id=request_id,
            request_hash=req_hash,
            expected_revision=expected_revision,
            actor=actor,
            audit_target="domain_gazetteer",
            mutator=_mutate,
        )

    def clear_gazetteer(
        self,
        project: dict,
        *,
        expected_revision: str = "",
        request_id: str = "",
        actor: str = "",
    ) -> CurationResultDTO:
        """Xóa sạch toàn bộ từ điển bí danh của dự án qua Commit Coordinator."""
        req_hash = sha("clear_gazetteer")[:16]

        def _mutate(cand: dict) -> dict[str, Any]:
            cleared = domain_clear_gazetteer(cand)
            return {
                "applied_count": cleared,
                "status": "applied" if cleared > 0 else "skipped",
                "note": f"cleared={cleared}",
            }

        return self._commit_gazetteer_mutation(
            project,
            operation="clear_gazetteer",
            request_id=request_id,
            request_hash=req_hash,
            expected_revision=expected_revision,
            actor=actor,
            audit_target="domain_gazetteer",
            mutator=_mutate,
        )

    def preload_gazetteer_template(
        self,
        project: dict,
        template_entries: dict[str, Any] | list[dict[str, Any]],
        *,
        source: str = "preloaded_template",
        overwrite_existing: bool = False,
        expected_revision: str = "",
        request_id: str = "",
        actor: str = "",
    ) -> CurationResultDTO:
        """Nạp bộ từ điển bí danh mẫu vào dự án qua Commit Coordinator."""
        return self.merge_gazetteer_entries(
            project,
            template_entries,
            source=source,
            overwrite_existing=overwrite_existing,
            expected_revision=expected_revision,
            request_id=request_id,
            actor=actor,
        )
