"""Bộ Chuẩn hóa Đích — Target Aligner (Target Alignment) cho phiên bản EDC + R."""
from __future__ import annotations

from typing import Any

from backend.domain.catalogs.service import compute_catalog_hash
from backend.integrations.embedder_gateway import EmbedderGateway, default_embedder
from backend.integrations.llm_gateway import LLMGateway
from backend.repositories.vector_repo import VectorIndexRepository
from shared.catalog_utils import relation_catalog
from shared.schemas.edc import AlignmentCandidateDTO
from shared.text_utils import normal, now_iso, sha


class TargetAligner:
    """Xếp hạng ứng viên và chuẩn hóa đề xuất EDC mở về danh mục đích."""

    def __init__(
        self,
        vector_repo: VectorIndexRepository | None = None,
        embedder: EmbedderGateway | None = None,
    ) -> None:
        self.vector_repo = vector_repo or VectorIndexRepository()
        self.embedder = embedder or default_embedder()

    def rank_candidates(
        self,
        project: dict,
        kind: str,
        open_name: str,
        open_definition: str,
        *,
        top_k: int = 5,
        embedder: EmbedderGateway | None = None,
    ) -> list[AlignmentCandidateDTO]:
        active_embedder = embedder or self.embedder
        project_id = str(project.get("project_id") or "default")
        catalog_items = relation_catalog(project) if kind == "relations" else project.get("entity_types", [])
        if not catalog_items:
            return []

        cat_hash = compute_catalog_hash(project, kind)
        model_fp = getattr(active_embedder, "fingerprint", "") or ""
        exact_norm = normal(open_name)
        hits = self.vector_repo.search(
            project_id,
            kind,
            catalog_items,
            open_name,
            active_embedder,
            mode="canon",
            open_definition=open_definition or open_name,
            top_k=max(top_k, 5),
        )

        candidates: list[AlignmentCandidateDTO] = []
        for hit in hits:
            score = float(hit.get("score", 0.0))
            if normal(hit.get("name", "")) == exact_norm:
                score = 1.0
            candidates.append(
                AlignmentCandidateDTO(
                    name=hit["name"],
                    definition=hit.get("definition", ""),
                    description=hit.get("description", ""),
                    score=score,
                    verified_by_llm=False,
                    reason="Trùng khớp tên chuẩn" if score >= 0.999 else f"Tương đồng ngữ nghĩa ({score:.2f})",
                    catalog_hash=cat_hash,
                    model_fingerprint=model_fp,
                )
            )
        candidates.sort(key=lambda c: -c.score)
        return candidates[:top_k]

    @staticmethod
    def build_verification_prompt(
        kind: str,
        open_name: str,
        open_definition: str,
        sample_evidence: str,
        candidates: list[AlignmentCandidateDTO],
    ) -> tuple[str, dict[str, str]]:
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        choice_map: dict[str, str] = {}
        options_lines: list[str] = []
        for idx, cand in enumerate(candidates[:5]):
            letter = letters[idx]
            choice_map[letter] = cand.name
            options_lines.append(f"{letter}. '{cand.name}': {cand.definition or cand.description}")
        none_letter = letters[len(choice_map)]
        choice_map[none_letter] = ""
        options_lines.append(f"{none_letter}. Không có mục nào tương đương (đây là khái niệm hoàn toàn mới).")

        label_vn = "quan hệ" if kind == "relations" else "loại thực thể"
        prompt = (
            f"Xác định xem {label_vn} mở '{open_name}' có tương đương ngữ nghĩa với mục nào trong danh mục chuẩn dưới đây không.\n"
            f"- Tên đề xuất mở: {open_name}\n"
            f"- Định nghĩa ngữ cảnh: {open_definition or '(không có)'}\n"
            f"- Ví dụ trích dẫn: {sample_evidence or '(không có)'}\n\n"
            "LỰA CHỌN:\n"
            + "\n".join(options_lines)
            + "\n\nChỉ trả lời đúng 1 chữ cái (A, B, C, ...):"
        )
        return prompt, choice_map

    def refresh_candidates_for_proposals(
        self,
        project: dict,
        *,
        proposal_ids: list[str],
        kind: str | None = None,
        candidate_threshold: float = 0.25,
        top_k: int = 5,
        embedder: EmbedderGateway | None = None,
    ) -> dict[str, Any]:
        """Làm mới gợi ý ứng viên cho đúng danh sách proposal_ids được chọn (không đổi trạng thái kiểm duyệt)."""
        active_embedder = embedder or self.embedder
        model_fp = getattr(active_embedder, "fingerprint", "") or ""
        unique_ids = list(dict.fromkeys(str(pid).strip() for pid in proposal_ids if str(pid).strip()))
        proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}

        refreshed_count = 0
        empty_candidates_count = 0
        error_count = 0
        item_results: list[dict[str, Any]] = []

        for pid in unique_ids:
            proposal = proposals_by_id.get(pid)
            if proposal is None:
                error_count += 1
                item_results.append(
                    {
                        "proposal_id": pid,
                        "status": "error",
                        "error": f"Không tìm thấy đề xuất ID '{pid}'",
                        "candidates_count": 0,
                    }
                )
                continue

            p_kind = str(proposal.get("kind", "relations"))
            if kind and p_kind != kind:
                error_count += 1
                item_results.append(
                    {
                        "proposal_id": pid,
                        "status": "error",
                        "error": f"Đề xuất '{proposal.get('name', pid)}' thuộc nhóm '{p_kind}', không thuộc '{kind}'",
                        "candidates_count": len(proposal.get("alignment_candidates", [])),
                    }
                )
                continue

            try:
                if active_embedder is None:
                    raise RuntimeError("Thiếu mô hình embedding để tìm ứng viên")
                open_name = str(proposal.get("name", ""))
                open_def = str(proposal.get("definition", ""))
                candidates = self.rank_candidates(
                    project,
                    p_kind,
                    open_name,
                    open_def,
                    top_k=top_k,
                    embedder=active_embedder,
                )
                filtered = [c for c in candidates if c.score >= candidate_threshold]
                cat_hash = compute_catalog_hash(project, p_kind)
                def_hash = sha(open_def.strip())[:16]

                proposal["alignment_candidates"] = [c.to_dict() for c in filtered]
                proposal["alignment_score"] = (
                    filtered[0].score if filtered else (candidates[0].score if candidates else 0.0)
                )
                proposal["candidates_catalog_hash"] = cat_hash
                proposal["candidates_model_fingerprint"] = model_fp
                proposal["candidates_definition_hash"] = def_hash
                proposal["candidates_refreshed_at"] = now_iso()
                proposal["last_refresh_error"] = ""

                refreshed_count += 1
                if not filtered:
                    empty_candidates_count += 1
                item_results.append(
                    {
                        "proposal_id": pid,
                        "status": "ok",
                        "error": "",
                        "candidates_count": len(filtered),
                        "top_candidate": filtered[0].name if filtered else "",
                        "top_score": filtered[0].score if filtered else 0.0,
                    }
                )
            except Exception as exc:
                error_count += 1
                proposal["last_refresh_error"] = str(exc)
                item_results.append(
                    {
                        "proposal_id": pid,
                        "status": "error",
                        "error": str(exc),
                        "candidates_count": len(proposal.get("alignment_candidates", [])),
                    }
                )

        return {
            "requested_count": len(unique_ids),
            "refreshed_count": refreshed_count,
            "empty_candidates_count": empty_candidates_count,
            "error_count": error_count,
            "item_results": item_results,
        }

    def align_project_proposals(
        self,
        project: dict,
        *,
        auto_align_threshold: float = 0.86,
        candidate_threshold: float = 0.45,
        enable_llm_verifier: bool = False,
        llm_params: dict | None = None,
        embedder: EmbedderGateway | None = None,
        proposal_ids: list[str] | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        active_embedder = embedder or self.embedder
        model_fp = getattr(active_embedder, "fingerprint", "") or ""
        auto_aligned_count = 0
        suggested_count = 0
        novel_count = 0
        error_count = 0
        allowed_ids = set(proposal_ids) if proposal_ids is not None else None

        for proposal in project.get("schema_proposals", []):
            if proposal.get("status") != "pending":
                continue
            if allowed_ids is not None and proposal.get("id") not in allowed_ids:
                continue
            p_kind = proposal.get("kind", "relations")
            if kind and p_kind != kind:
                continue

            open_name = str(proposal.get("name", ""))
            open_def = str(proposal.get("definition", ""))
            try:
                if active_embedder is None:
                    raise RuntimeError("Thiếu mô hình embedding")
                candidates = self.rank_candidates(
                    project,
                    p_kind,
                    open_name,
                    open_def,
                    top_k=5,
                    embedder=active_embedder,
                )
            except Exception as exc:
                proposal["last_refresh_error"] = str(exc)
                error_count += 1
                continue

            cat_hash = compute_catalog_hash(project, p_kind)
            def_hash = sha(open_def.strip())[:16]
            filtered = [c for c in candidates if c.score >= candidate_threshold]
            proposal["alignment_candidates"] = [c.to_dict() for c in filtered]
            proposal["candidates_catalog_hash"] = cat_hash
            proposal["candidates_model_fingerprint"] = model_fp
            proposal["candidates_definition_hash"] = def_hash
            proposal["candidates_refreshed_at"] = now_iso()
            proposal["last_refresh_error"] = ""

            if not filtered:
                proposal["alignment_score"] = candidates[0].score if candidates else 0.0
                proposal["auto_aligned"] = False
                novel_count += 1
                continue

            best = filtered[0]
            proposal["alignment_score"] = best.score
            should_auto_align = best.score >= auto_align_threshold
            chosen_target = best.name
            verified_by_llm = False

            if enable_llm_verifier and llm_params and best.score >= candidate_threshold:
                obs = proposal.get("observations") or []
                sample_ev = obs[0].get("evidence", "") if obs else ""
                v_prompt, choice_map = self.build_verification_prompt(p_kind, open_name, open_def, sample_ev, filtered)
                try:
                    letter = LLMGateway.verify_alignment_choice(
                        llm_params.get("provider", ""),
                        llm_params.get("api_key", ""),
                        llm_params.get("model", ""),
                        v_prompt,
                        list(choice_map.keys()),
                        base_url=llm_params.get("base_url", ""),
                        client=llm_params.get("client"),
                    )
                    if letter and choice_map.get(letter):
                        chosen_target = choice_map[letter]
                        should_auto_align = True
                        verified_by_llm = True
                        for cand_dict in proposal["alignment_candidates"]:
                            if cand_dict.get("name") == chosen_target:
                                cand_dict["verified_by_llm"] = True
                    elif letter and choice_map.get(letter) == "":
                        should_auto_align = False
                except Exception as exc:
                    proposal["last_refresh_error"] = str(exc)
                    error_count += 1
                    should_auto_align = False

            if should_auto_align and chosen_target:
                proposal["status"] = "merged"
                proposal["canonical_name"] = chosen_target
                proposal["auto_aligned"] = True
                proposal["decision_origin"] = "llm_verified_auto" if verified_by_llm else "auto_align"
                proposal["review_note"] = f"[Target Alignment tự động] Khớp '{chosen_target}' (score={best.score:.2f})"
                pid = proposal["id"]
                if p_kind == "relations":
                    for edge in project.get("edges", []):
                        if pid in edge.get("schema_proposal_ids", []):
                            edge["relation"] = chosen_target
                else:
                    for node in project.get("nodes", []):
                        if pid in node.get("schema_proposal_ids", []):
                            node["kind"] = chosen_target
                auto_aligned_count += 1
            else:
                proposal["auto_aligned"] = False
                suggested_count += 1

        return {
            "auto_aligned": auto_aligned_count,
            "suggested_for_review": suggested_count,
            "novel_proposals": novel_count,
            "error_count": error_count,
        }
