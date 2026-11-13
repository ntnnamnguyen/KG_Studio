"""Logic lọc, sắp xếp, phân trang và tạo dữ liệu bảng cho Bảng Duyệt EDC."""
from __future__ import annotations

import json
from typing import Any

from backend.domain.catalogs.service import (
    batch_proposal_impacts,
    compute_catalog_hash,
    is_proposal_candidates_stale,
)
from frontend.components.shared_curation_ui import paginate_items
from shared.text_utils import normal, sha

STATUS_LABELS_VN = {
    "pending": "Chờ duyệt (pending)",
    "approved": "Đã duyệt mới (approved)",
    "merged": "Đã hợp nhất (merged)",
    "rejected": "Đã từ chối (rejected)",
}


def status_label_vn(status: str) -> str:
    """Chuyển mã trạng thái proposal sang nhãn tiếng Việt dễ đọc."""
    return STATUS_LABELS_VN.get(str(status or "pending"), str(status or "pending"))


def verification_badge_label(
    project: dict,
    proposal: dict,
    *,
    current_model_fingerprint: str = "",
    precomputed_cat_hash: str | None = None,
) -> str:
    """Phân biệt rõ: gợi ý vector, đã được LLM kiểm tra, tự động hợp nhất, con người quyết định, hoặc gợi ý cũ."""
    origin = str(proposal.get("decision_origin") or "")
    status = str(proposal.get("status") or "pending")
    auto_aligned = bool(proposal.get("auto_aligned", False))
    cands = proposal.get("alignment_candidates") or []

    if status in ("approved", "merged", "rejected") and origin == "human":
        return "Con người quyết định"
    if auto_aligned or origin in ("auto_align", "llm_verified_auto"):
        if origin == "llm_verified_auto" or any(c.get("verified_by_llm") for c in cands):
            return "Tự động hợp nhất (LLM đã kiểm tra)"
        return "Tự động hợp nhất (Vector)"
    if status in ("approved", "merged", "rejected") and not auto_aligned:
        return "Con người quyết định"

    if not cands:
        if proposal.get("last_refresh_error"):
            return "Lỗi làm mới gợi ý"
        return "Chưa có gợi ý"

    stale, _ = is_proposal_candidates_stale(
        project,
        proposal,
        current_model_fingerprint,
        precomputed_cat_hash=precomputed_cat_hash,
    )
    suffix = " [Gợi ý cũ]" if stale else ""
    if any(c.get("verified_by_llm") for c in cands):
        return f"Đã được LLM kiểm tra{suffix}"
    return f"Gợi ý vector{suffix}"


def compute_filter_signature(filters: dict[str, Any]) -> str:
    """Chữ ký xác định cho bộ lọc (không tính page và sort_by để đổi trang/sắp xếp vẫn giữ nguyên lựa chọn)."""
    relevant = {
        "status": str(filters.get("status", "pending")),
        "search": normal(str(filters.get("search", ""))),
        "doc_id": str(filters.get("doc_id", "all")),
        "candidate_filter": str(filters.get("candidate_filter", "all")),
        "definition_filter": str(filters.get("definition_filter", "all")),
        "origin_filter": str(filters.get("origin_filter", "all")),
    }
    return sha(json.dumps(relevant, ensure_ascii=False, sort_keys=True))[:16]


def filter_and_sort_proposals(
    project: dict,
    kind: str,
    filters: dict[str, Any],
) -> list[dict]:
    """Lọc và sắp xếp đề xuất của đúng nhóm `kind`."""
    all_for_kind = [p for p in project.get("schema_proposals", []) if p.get("kind") == kind]
    status_f = str(filters.get("status", "pending") or "pending")
    search_q = normal(str(filters.get("search", "")))
    doc_f = str(filters.get("doc_id", "all") or "all")
    cand_f = str(filters.get("candidate_filter", "all") or "all")
    def_f = str(filters.get("definition_filter", "all") or "all")
    origin_f = str(filters.get("origin_filter", "all") or "all")
    sort_by = str(filters.get("sort_by", "name") or "name")
    sort_desc = bool(filters.get("sort_desc", False))

    filtered: list[dict] = []
    for prop in all_for_kind:
        p_status = str(prop.get("status", "pending"))
        if status_f != "all" and p_status != status_f:
            continue

        if search_q:
            haystack = " ".join(
                [
                    normal(str(prop.get("name", ""))),
                    normal(str(prop.get("canonical_name", ""))),
                    normal(str(prop.get("definition", ""))),
                    normal(str(prop.get("description", ""))),
                ]
            )
            if search_q not in haystack:
                continue

        if doc_f != "all":
            obs_docs = {str(o.get("doc_id", "")) for o in prop.get("observations", []) if o.get("doc_id")}
            if doc_f not in obs_docs:
                continue

        cands = prop.get("alignment_candidates") or []
        if cand_f == "has_candidates" and not cands:
            continue
        if cand_f == "no_candidates" and cands:
            continue

        has_def = bool(str(prop.get("definition", "")).strip())
        if def_f == "missing_definition" and has_def:
            continue
        if def_f == "has_definition" and not has_def:
            continue

        is_auto = bool(prop.get("auto_aligned", False)) or prop.get("decision_origin") in (
            "auto_align",
            "llm_verified_auto",
        )
        is_human = p_status in ("approved", "merged", "rejected") and not is_auto
        if origin_f == "auto_aligned" and not is_auto:
            continue
        if origin_f == "human_decided" and not is_human:
            continue
        if origin_f == "undecided" and is_human:
            continue

        filtered.append(prop)

    # Chỉ tính reverse impact khi người dùng sắp xếp theo số lượng cạnh bị ảnh hưởng
    impact_cache = batch_proposal_impacts(project, [p["id"] for p in filtered]) if (sort_by == "impact_edges") else {}

    def _sort_key(p: dict) -> Any:
        if sort_by == "impact_edges":
            return (len(impact_cache[p["id"]]["edges"]), len(impact_cache[p["id"]]["nodes"]), normal(p.get("name", "")))
        if sort_by == "alignment_score":
            cands = p.get("alignment_candidates") or []
            top_score = float(cands[0].get("score", 0.0)) if cands else float(p.get("alignment_score", 0.0) or 0.0)
            return (top_score, normal(p.get("name", "")))
        return normal(p.get("name", ""))

    return sorted(filtered, key=_sort_key, reverse=sort_desc)


def paginate_proposals(
    proposals: list[dict],
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int, int]:
    """Phân trang danh sách đề xuất; sử dụng hàm paginate_items dùng chung."""
    return paginate_items(proposals, page=page, page_size=page_size)


def build_table_display_rows(
    project: dict,
    proposals: list[dict],
    selected_ids: set[str],
    *,
    current_model_fingerprint: str = "",
) -> list[dict[str, Any]]:
    """Tạo dữ liệu bảng hiển thị chuẩn 10 cột theo đặc tả mục 2.1."""
    if not proposals:
        return []
    impacts_map = batch_proposal_impacts(project, [str(p.get("id", "")) for p in proposals])
    cat_hash_by_kind: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for prop in proposals:
        pid = str(prop.get("id", ""))
        p_kind = str(prop.get("kind") or "relations")
        if p_kind not in cat_hash_by_kind:
            cat_hash_by_kind[p_kind] = compute_catalog_hash(project, p_kind)
        impact = impacts_map.get(pid, {"nodes": [], "edges": [], "direct_edges": [], "indirect_edges": []})
        cands = prop.get("alignment_candidates") or []
        top_cand_name = str(cands[0].get("name", "")) if cands else "Chưa có"
        top_score = float(cands[0].get("score", 0.0)) if cands else float(prop.get("alignment_score", 0.0) or 0.0)
        score_text = f"{top_score:.2f}" if (cands or top_score > 0.0) else "—"

        raw_def = str(prop.get("definition") or prop.get("description") or "").strip()
        short_def = (raw_def[:90] + "…") if len(raw_def) > 90 else (raw_def or "(Thiếu định nghĩa)")

        obs = prop.get("observations") or []
        doc_ids = {str(o.get("doc_id", "")) for o in obs if o.get("doc_id")}
        indirect_cnt = len(impact.get("indirect_edges", []))
        impact_label = f"{len(impact['nodes'])} node · {len(impact['edges'])} cạnh"
        if indirect_cnt > 0:
            impact_label += f" ({indirect_cnt} gián tiếp)"

        rows.append(
            {
                "id": pid,
                "Chọn": pid in selected_ids,
                "Tên đề xuất": str(prop.get("name", "")),
                "Mô tả / Định nghĩa": short_def,
                "Ứng viên đích": top_cand_name,
                "Điểm tương đồng": score_text,
                "Xác thực": verification_badge_label(
                    project,
                    prop,
                    current_model_fingerprint=current_model_fingerprint,
                    precomputed_cat_hash=cat_hash_by_kind[p_kind],
                ),
                "Trạng thái": status_label_vn(str(prop.get("status", "pending"))),
                "Tên chuẩn": str(prop.get("canonical_name", "")) or "—",
                "Ảnh hưởng": impact_label,
                "Nguồn": f"{len(doc_ids) or (1 if obs else 0)} tài liệu / {len(obs)} quan sát",
            }
        )
    return rows
