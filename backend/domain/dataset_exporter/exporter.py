"""Chuyển đổi quyết định kiểm duyệt của con người đã commit thành dữ liệu huấn luyện cho ML Lab."""
from __future__ import annotations

import json
from pathlib import Path

from backend.domain.catalogs.service import schema_review_issue
from shared.catalog_utils import relation_catalog
from shared.config_loader import APP_ROOT
from shared.constants import STATUS_APPROVED, STATUS_REJECTED
from shared.prompt_templates import format_canon_query, format_catalog_passage, format_sr_query
from shared.schemas.curation import NON_SEMANTIC_REJECTION_CODES
from shared.schemas.training_records import (
    CanonicalizationPairRecord,
    SFTInstructionRecord,
    SRTripletRecord,
)
from shared.text_utils import normal

DEFAULT_EXPORT_DIR = APP_ROOT / "data" / "training_exports"


def _is_human_committed_proposal(proposal: dict) -> bool:
    """Chỉ chấp nhận đề xuất do con người đã duyệt và commit, loại trừ auto_aligned / preview / draft."""
    status = str(proposal.get("status", ""))
    if status not in ("merged", "approved"):
        return False
    origin = str(proposal.get("decision_origin", ""))
    if origin in ("auto_align", "llm_verified_auto", "preview", "draft"):
        return False
    if bool(proposal.get("auto_aligned", False)) and origin != "human":
        return False
    return True


class ActiveLearningExporter:
    def __init__(self, export_dir: str | Path | None = None) -> None:
        self.export_dir = Path(export_dir) if export_dir else DEFAULT_EXPORT_DIR
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def build_sr_triplets(self, project: dict) -> list[SRTripletRecord]:
        project_id = str(project.get("project_id", ""))
        rel_catalog = relation_catalog(project)
        if len(rel_catalog) < 2:
            return []

        passage_by_name = {
            normal(r["name"]): (
                r["name"],
                format_catalog_passage(r["name"], r.get("definition", ""), r.get("description", "")),
            )
            for r in rel_catalog
        }
        all_norm_names = list(passage_by_name.keys())

        edges = project.get("edges", [])
        approved_by_chunk: dict[tuple[str, str], set[str]] = {}
        rejected_by_chunk: dict[tuple[str, str], set[str]] = {}
        non_semantic_rejected_by_chunk: dict[tuple[str, str], set[str]] = {}
        evidence_by_chunk: dict[tuple[str, str], list[str]] = {}

        for edge in edges:
            doc_id = str(edge.get("doc_id", ""))
            chunk_key = str(edge.get("chunk_hash") or edge.get("chunk_number") or "")
            rel_norm = normal(edge.get("relation", ""))
            if not rel_norm or rel_norm not in passage_by_name:
                continue
            key = (doc_id, chunk_key)
            ev = str(edge.get("evidence", "")).strip()
            if ev:
                evidence_by_chunk.setdefault(key, []).append(ev)
            # Chỉ lấy cạnh đã được con người duyệt (STATUS_APPROVED) và không vướng lỗi schema EDC
            if edge.get("status") == STATUS_APPROVED and not schema_review_issue(project, edge):
                approved_by_chunk.setdefault(key, set()).add(rel_norm)
            elif edge.get("status") == STATUS_REJECTED:
                rej_code = str(edge.get("rejection_code") or "").strip()
                if rej_code in NON_SEMANTIC_REJECTION_CODES:
                    # Loại bỏ vì Ngoài phạm vi bài toán / Trùng lặp dữ kiện -> không dùng làm mẫu âm ngữ nghĩa
                    non_semantic_rejected_by_chunk.setdefault(key, set()).add(rel_norm)
                else:
                    rejected_by_chunk.setdefault(key, set()).add(rel_norm)

        records: list[SRTripletRecord] = []
        for idx, ((doc_id, chunk_key), pos_norms) in enumerate(approved_by_chunk.items()):
            evidences = evidence_by_chunk.get((doc_id, chunk_key), [])
            if not evidences:
                continue
            context_text = " ".join(dict.fromkeys(evidences))
            query_text = format_sr_query(context_text)

            non_sem = non_semantic_rejected_by_chunk.get((doc_id, chunk_key), set())
            hard_negs = [
                n
                for n in rejected_by_chunk.get((doc_id, chunk_key), set())
                if n not in pos_norms and n not in non_sem
            ]
            fallback_negs = [n for n in all_norm_names if n not in pos_norms and n not in non_sem]
            neg_pool = hard_negs if hard_negs else fallback_negs
            if not neg_pool:
                continue

            for pos_idx, pos_norm in enumerate(sorted(pos_norms)):
                neg_norm = neg_pool[(idx + pos_idx) % len(neg_pool)]
                pos_name, pos_passage = passage_by_name[pos_norm]
                neg_name, neg_passage = passage_by_name[neg_norm]
                records.append(
                    SRTripletRecord(
                        query_text=query_text,
                        positive_name=pos_name,
                        positive_passage=pos_passage,
                        negative_name=neg_name,
                        negative_passage=neg_passage,
                        project_id=project_id,
                        doc_id=doc_id,
                        chunk_hash=chunk_key,
                    )
                )
        return records

    def build_rejected_negative_pairs(self, project: dict) -> list[dict]:
        """Từ chối đề xuất chỉ tạo negative pair khi có đích so sánh cụ thể và lý do kiểm duyệt."""
        project_id = str(project.get("project_id", ""))
        rel_map = {
            normal(r["name"]): format_catalog_passage(r["name"], r.get("definition", ""), r.get("description", ""))
            for r in relation_catalog(project)
        }
        type_map = {
            normal(t["name"]): format_catalog_passage(t["name"], t.get("definition", ""), t.get("description", ""))
            for t in project.get("entity_types", [])
        }
        negatives: list[dict] = []
        for proposal in project.get("schema_proposals", []):
            if proposal.get("status") != "rejected":
                continue
            if proposal.get("decision_origin") in ("preview", "draft", "auto_align"):
                continue
            compared_target = str(proposal.get("compared_target") or "").strip()
            reason = str(proposal.get("review_note") or "").strip()
            if not compared_target or not reason:
                continue
            kind = str(proposal.get("kind", "relations"))
            target_map = rel_map if kind == "relations" else type_map
            target_norm = normal(compared_target)
            if target_norm not in target_map:
                continue
            open_name = str(proposal.get("name", "")).strip()
            open_def = str(proposal.get("definition", "")).strip()
            negatives.append(
                {
                    "kind": kind,
                    "open_name": open_name,
                    "open_definition": open_def,
                    "query_text": format_canon_query(open_name, open_def or open_name),
                    "rejected_target": compared_target,
                    "rejected_passage": target_map[target_norm],
                    "reason": reason,
                    "project_id": project_id,
                }
            )
        return negatives

    def build_canonicalization_pairs(self, project: dict) -> list[CanonicalizationPairRecord]:
        project_id = str(project.get("project_id", ""))
        rel_map = {
            normal(r["name"]): format_catalog_passage(r["name"], r.get("definition", ""), r.get("description", ""))
            for r in relation_catalog(project)
        }
        type_map = {
            normal(t["name"]): format_catalog_passage(t["name"], t.get("definition", ""), t.get("description", ""))
            for t in project.get("entity_types", [])
        }

        pairs: list[CanonicalizationPairRecord] = []
        for proposal in project.get("schema_proposals", []):
            if not _is_human_committed_proposal(proposal):
                continue
            status = str(proposal.get("status", ""))
            kind = str(proposal.get("kind", "relations"))
            open_name = str(proposal.get("name", "")).strip()
            open_def = str(proposal.get("definition", "")).strip()
            canon_name = str(proposal.get("canonical_name", "")).strip() or open_name
            target_map = rel_map if kind == "relations" else type_map
            canon_norm = normal(canon_name)
            if canon_norm not in target_map:
                # Đích đã bị xóa hoặc thay thế khỏi catalog hiện hành -> không xuất nhãn cũ
                continue
            canon_passage = target_map[canon_norm]
            negatives = [p for k, p in target_map.items() if k != canon_norm][:3]

            pairs.append(
                CanonicalizationPairRecord(
                    kind=kind,
                    open_name=open_name,
                    open_definition=open_def,
                    query_text=format_canon_query(open_name, open_def or open_name),
                    canonical_name=canon_name,
                    canonical_passage=canon_passage,
                    negative_passages=negatives,
                    action=status,
                    project_id=project_id,
                )
            )
        return pairs

    def build_sft_records(self, project: dict) -> list[SFTInstructionRecord]:
        project_id = str(project.get("project_id", ""))
        nodes_by_id = {n["id"]: n for n in project.get("nodes", [])}
        # Chỉ lấy các cạnh đã được con người duyệt (STATUS_APPROVED) và hợp lệ theo schema
        approved_edges = [
            e
            for e in project.get("edges", [])
            if e.get("status") == STATUS_APPROVED and not schema_review_issue(project, e)
        ]
        if not approved_edges:
            return []

        by_doc: dict[str, list[dict]] = {}
        for edge in approved_edges:
            by_doc.setdefault(str(edge.get("doc_id", "")), []).append(edge)

        records: list[SFTInstructionRecord] = []
        for doc_id, edges in by_doc.items():
            node_ids = {x for e in edges for x in (e.get("source"), e.get("target")) if x in nodes_by_id}
            thuc_the = [
                {"ten": nodes_by_id[nid]["name"], "loai": nodes_by_id[nid].get("kind", ""), "mo_ta": nodes_by_id[nid].get("description", "")}
                for nid in sorted(node_ids)
            ]
            quan_he = [
                {
                    "nguon": nodes_by_id[e["source"]]["name"],
                    "quan_he": e.get("relation", ""),
                    "dich": nodes_by_id[e["target"]]["name"],
                    "trich_dan": e.get("evidence", ""),
                }
                for e in edges
                if e.get("source") in nodes_by_id and e.get("target") in nodes_by_id
            ]
            context = "\n".join(dict.fromkeys(e.get("evidence", "") for e in edges if e.get("evidence")))
            # Xác định system_prompt theo provenance của run thực tế nếu có
            matched_run = next((r for r in reversed(project.get("runs", [])) if r.get("doc_id") == doc_id), None)
            if matched_run and isinstance(matched_run.get("prepared_request"), dict) and matched_run["prepared_request"].get("system_prompt"):
                sys_prompt = matched_run["prepared_request"]["system_prompt"]
            else:
                from backend.domain.prompts.service import get_active_prompt_content
                sys_prompt = get_active_prompt_content(project, project.get("extraction_mode", "closed"))

            records.append(
                SFTInstructionRecord(
                    system_prompt=sys_prompt,
                    chunk_text=context,
                    retrieved_relations=sorted({e.get("relation", "") for e in edges if e.get("relation")}),
                    target_json={"thuc_the": thuc_the, "quan_he": quan_he},
                    project_id=project_id,
                    doc_id=doc_id,
                    chunk_number=1,
                )
            )
        return records

    def export_project(self, project: dict) -> dict:
        sr_records = self.build_sr_triplets(project)
        canon_records = self.build_canonicalization_pairs(project)
        sft_records = self.build_sft_records(project)

        sr_path = self.export_dir / "sr_triplets.jsonl"
        canon_path = self.export_dir / "canonicalization_pairs.jsonl"
        sft_path = self.export_dir / "sft_extractions.jsonl"

        sr_path.write_text(
            "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in sr_records) + ("\n" if sr_records else ""),
            encoding="utf-8",
        )
        canon_path.write_text(
            "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in canon_records) + ("\n" if canon_records else ""),
            encoding="utf-8",
        )
        sft_path.write_text(
            "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in sft_records) + ("\n" if sft_records else ""),
            encoding="utf-8",
        )

        return {
            "sr_triplets_count": len(sr_records),
            "canonicalization_pairs_count": len(canon_records),
            "sft_records_count": len(sft_records),
            "files": {
                "sr_triplets": str(sr_path),
                "canonicalization_pairs": str(canon_path),
                "sft_extractions": str(sft_path),
            },
        }
