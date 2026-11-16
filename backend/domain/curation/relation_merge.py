"""Các thuật toán và thao tác Gộp Quan hệ (Relation Merge), Thu gọn Cạnh trùng (Collapse Edges) và Quản lý Cặp nghi trùng."""
from __future__ import annotations

from collections import Counter
import copy
from difflib import SequenceMatcher
from typing import Any

from backend.domain.catalogs.service import compute_project_revision
from shared.constants import STATUS_REJECTED
from shared.schemas.curation import CurationResultDTO
from shared.text_utils import normal, now_iso, sha, uid

from .entities import clear_duplicate_suggestions_cache
from .merge_core import (
    _clone_project_for_merge_mutation,
    consolidate_edge_evidences,
    filter_dismissed_pairs,
    flatten_redirects,
    generate_candidate_index_pairs,
    group_edges_by_triplet,
    normalize_pair_key,
    rank_representative_edge,
    score_text_pair_similarity,
    sort_edges_by_priority,
    update_redirect_map,
)

# Bộ nhớ đệm gợi ý quan hệ nghi trùng theo (project_id, revision, fuzzy_threshold)
_RELATION_DUPLICATE_SUGGESTIONS_CACHE: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
# Bộ nhớ đệm gợi ý bộ ba (cạnh lặp) nghi trùng theo (project_id, revision, fuzzy_threshold, include_fuzzy, include_inverse)
_TRIPLE_DUPLICATE_SUGGESTIONS_CACHE: dict[tuple[str, str, float, bool, bool], list[dict[str, Any]]] = {}


def clear_relation_duplicate_suggestions_cache() -> None:
    """Xóa toàn bộ bộ nhớ đệm gợi ý trùng lặp quan hệ và bộ ba cạnh."""
    _RELATION_DUPLICATE_SUGGESTIONS_CACHE.clear()
    _TRIPLE_DUPLICATE_SUGGESTIONS_CACHE.clear()


def relation_duplicate_suggestions(
    project: dict,
    fuzzy_threshold: float = 0.75,
    *,
    include_dismissed: bool = False,
) -> list[dict[str, Any]]:
    """Phát hiện các cặp quan hệ nghi trùng hoặc tương đồng cao trong đồ thị và danh mục."""
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    rev = compute_project_revision(project)
    cache_key = (proj_id, rev, float(fuzzy_threshold))

    if cache_key not in _RELATION_DUPLICATE_SUGGESTIONS_CACHE:
        redirects = project.get("relation_redirects", {})
        edges = project.get("edges", [])
        edge_counts = Counter(str(e.get("relation", "")).strip() for e in edges if e.get("relation"))
        catalog_rels = {
            str(r.get("name", "")).strip() if isinstance(r, dict) else str(r).strip()
            for r in (project.get("relation_types") or []) + (project.get("relations") or [])
            if (isinstance(r, dict) and r.get("name")) or (isinstance(r, str) and r.strip())
        }

        all_rels_set = {
            r for r in (set(edge_counts.keys()) | catalog_rels)
            if r and r not in redirects and (edge_counts.get(r, 0) > 0 or r in catalog_rels)
        }
        all_rels = sorted(all_rels_set)
        n_rels = len(all_rels)
        norms = [normal(r) for r in all_rels]
        cleans = [n_val.replace("_", " ").strip() for n_val in norms]
        words_list = [set(c_val.split()) for c_val in cleans]

        candidate_pairs = generate_candidate_index_pairs(
            cleans,
            fuzzy_threshold=fuzzy_threshold,
            force_all_threshold=120,
            max_bucket_size=80,
        )
        pair_iter = sorted(candidate_pairs)

        pairs: list[dict[str, Any]] = []

        for i, j in pair_iter:
            r1 = all_rels[i]
            r2 = all_rels[j]

            if r1 in redirects or r2 in redirects:
                continue
            if redirects.get(r1) == r2 or redirects.get(r2) == r1:
                continue
            if redirects.get(r1) and redirects.get(r1) == redirects.get(r2):
                continue

            norm_1 = norms[i]
            norm_2 = norms[j]
            clean_1 = cleans[i]
            clean_2 = cleans[j]

            reasons: list[str] = []
            score = 0.0

            if norm_1 == norm_2:
                reasons.append("Trùng tên chuẩn hóa")
                score = 1.0
            elif clean_1 == clean_2:
                reasons.append("Trùng tên khi chuẩn hóa khoảng trắng/gạch dưới")
                score = 0.98
            else:
                is_sub = min(len(clean_1), len(clean_2)) >= 4 and (clean_1 in clean_2 or clean_2 in clean_1)
                sm = SequenceMatcher(None, clean_1, clean_2)
                if is_sub:
                    ratio = sm.ratio()
                    reasons.append("Chứa nhau (tiền tố/hậu tố)")
                    score = max(0.85, ratio)
                elif sm.real_quick_ratio() >= fuzzy_threshold and sm.quick_ratio() >= fuzzy_threshold:
                    ratio = sm.ratio()
                    if ratio >= fuzzy_threshold:
                        reasons.append(f"Độ giống tên cao ({ratio:.2f})")
                        score = ratio

                w1 = words_list[i]
                w2 = words_list[j]
                if w1 and w2:
                    inter_len = len(w1 & w2)
                    if inter_len > 0:
                        union_len = len(w1) + len(w2) - inter_len
                        jaccard = inter_len / union_len
                        if jaccard >= 0.65 and jaccard > score:
                            reasons.append(f"Trùng {inter_len}/{union_len} từ khóa")
                            score = max(score, jaccard)

            if reasons and score >= fuzzy_threshold:
                cnt_1 = edge_counts.get(r1, 0)
                cnt_2 = edge_counts.get(r2, 0)

                if cnt_1 > cnt_2:
                    target, source = r1, r2
                elif cnt_2 > cnt_1:
                    target, source = r2, r1
                elif r1 in catalog_rels and r2 not in catalog_rels:
                    target, source = r1, r2
                elif r2 in catalog_rels and r1 not in catalog_rels:
                    target, source = r2, r1
                else:
                    target = r1 if len(r1) >= len(r2) else r2
                    source = r2 if target == r1 else r1

                pair_fp = sha(f"{min(norm_1, norm_2)}::{max(norm_1, norm_2)}")[:16]
                pairs.append(
                    {
                        "pair_key": f"{r1} ↔ {r2}",
                        "pair_fingerprint": pair_fp,
                        "relation_a": r1,
                        "relation_b": r2,
                        "count_a": cnt_1,
                        "count_b": cnt_2,
                        "target": target,
                        "source": source,
                        "suggested_target": target,
                        "suggested_drop": source,
                        "score": round(score, 2),
                        "reason": "; ".join(reasons),
                    }
                )

        pairs.sort(key=lambda x: -x["score"])
        if len(_RELATION_DUPLICATE_SUGGESTIONS_CACHE) > 32:
            _RELATION_DUPLICATE_SUGGESTIONS_CACHE.clear()
        _RELATION_DUPLICATE_SUGGESTIONS_CACHE[cache_key] = pairs

    all_pairs = [dict(p) for p in _RELATION_DUPLICATE_SUGGESTIONS_CACHE[cache_key]]
    return filter_dismissed_pairs(
        all_pairs,
        project.get("not_duplicate_relation_pairs", []),
        id_a_key="relation_a",
        id_b_key="relation_b",
        fp_key="",
        include_dismissed=include_dismissed,
        use_normal=True,
    )


_PASSIVE_MARKERS = ("được ", "bị ", "do ", "duoc ", "bi ")
_PASSIVE_STOPWORDS = {
    "được", "bị", "do", "bởi", "cho", "vào", "tại", "ở", "của", "là",
    "duoc", "bi", "boi", "vao", "tai", "o", "cua", "la",
}


def _build_triple_group_record(
    group_edges: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    *,
    match_type: str,
    match_type_label: str,
    score: float,
    reason: str,
    canonical_relation: str = "",
    preferred_rep_id: str = "",
) -> dict[str, Any]:
    """Đóng gói một nhóm cạnh nghi trùng thành bản ghi gợi ý chuẩn hóa (tái sử dụng sort_edges_by_priority)."""
    sorted_edges = sort_edges_by_priority(group_edges)
    rep = next((e for e in sorted_edges if str(e.get("id", "")) == preferred_rep_id), sorted_edges[0])
    rep_id = str(rep.get("id", ""))
    src_id = str(rep.get("source", "")).strip()
    tgt_id = str(rep.get("target", "")).strip()
    src_name = str(nodes_by_id.get(src_id, {}).get("name") or src_id)
    tgt_name = str(nodes_by_id.get(tgt_id, {}).get("name") or tgt_id)
    chosen_rel = canonical_relation or str(rep.get("relation", "")).strip()

    all_ids_sorted = sorted(str(e.get("id", "")) for e in sorted_edges if e.get("id"))
    edge_a_id = all_ids_sorted[0] if all_ids_sorted else rep_id
    edge_b_id = "|".join(all_ids_sorted[1:]) if len(all_ids_sorted) > 1 else rep_id
    distinct_rels = list(dict.fromkeys(str(e.get("relation", "")).strip() for e in sorted_edges if e.get("relation")))
    statuses = [str(e.get("status", "")) for e in sorted_edges]

    return {
        "group_key": f"{match_type}::{src_id}::{normal(chosen_rel)}::{tgt_id}::{'_'.join(all_ids_sorted)}",
        "edge_a_id": edge_a_id,
        "edge_b_id": edge_b_id,
        "pair_fingerprint": sha("::".join(all_ids_sorted))[:16],
        "match_type": match_type,
        "match_type_label": match_type_label,
        "score": round(float(score), 2),
        "reason": reason,
        "source": src_id,
        "source_name": src_name,
        "relation": chosen_rel,
        "relation_variants": distinct_rels,
        "target": tgt_id,
        "target_name": tgt_name,
        "representative_id": rep_id,
        "representative_status": str(rep.get("status", "")),
        "status_summary": ", ".join(statuses),
        "edge_ids": [str(e.get("id", "")) for e in sorted_edges],
        "dropped_ids": [str(e.get("id", "")) for e in sorted_edges if str(e.get("id", "")) != rep_id],
        "count": len(sorted_edges),
        "evidences": [
            {
                "edge_id": str(e.get("id", "")),
                "source": str(e.get("source", "")),
                "target": str(e.get("target", "")),
                "relation": str(e.get("relation", "")),
                "doc_id": e.get("doc_id", ""),
                "doc_name": e.get("doc_name", ""),
                "chunk_number": e.get("chunk_number", 0),
                "start_char": e.get("start_char"),
                "end_char": e.get("end_char"),
                "evidence": e.get("evidence", ""),
                "status": e.get("status", ""),
            }
            for e in sorted_edges
        ],
    }


def triple_duplicate_suggestions(
    project: dict,
    fuzzy_threshold: float = 0.70,
    *,
    include_dismissed: bool = False,
    include_fuzzy_same_endpoints: bool = True,
    include_inverse_pairs: bool = True,
) -> list[dict[str, Any]]:
    """Phát hiện và chấm điểm gợi ý các nhóm bộ ba (cạnh) nghi trùng lặp theo 3 tầng:
    1. exact_triplet (Score = 1.00): Cùng (source, normal(relation), target).
    2. fuzzy_relation (Score >= fuzzy_threshold): Cùng (source, target), vị từ tương đồng/đồng nghĩa bề mặt.
    3. inverse_pair (Score >= max(0.65, fuzzy_threshold)): Ngược chiều Chủ động – Bị động giữa cùng 2 thực thể.
    Tái sử dụng group_edges_by_triplet, score_text_pair_similarity, sort_edges_by_priority và filter_dismissed_pairs.
    """
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    rev = compute_project_revision(project)
    eff_thresh = float(fuzzy_threshold)
    cache_key = (
        proj_id,
        rev,
        eff_thresh,
        bool(include_fuzzy_same_endpoints),
        bool(include_inverse_pairs),
    )

    if cache_key not in _TRIPLE_DUPLICATE_SUGGESTIONS_CACHE:
        nodes_by_id = {str(n.get("id", "")): n for n in project.get("nodes", [])}
        active_edges = [
            e for e in project.get("edges", [])
            if e.get("status") != STATUS_REJECTED
            and str(e.get("source", "")).strip()
            and str(e.get("relation", "")).strip()
            and str(e.get("target", "")).strip()
        ]

        suggestions: list[dict[str, Any]] = []
        seen_edge_sets: set[tuple[str, ...]] = set()

        # Tầng 1: Trùng bộ ba tuyệt đối (source, normal(relation), target)
        exact_groups = group_edges_by_triplet(active_edges, exclude_rejected=True)
        for (_, _, _), items in exact_groups.items():
            if len(items) > 1:
                sig = tuple(sorted(str(e.get("id", "")) for e in items))
                seen_edge_sets.add(sig)
                suggestions.append(
                    _build_triple_group_record(
                        items,
                        nodes_by_id,
                        match_type="exact_triplet",
                        match_type_label="Trùng bộ ba 100%",
                        score=1.0,
                        reason=f"Trùng khớp 100% Nguồn – Quan hệ – Đích ({len(items)} cạnh)",
                    )
                )

        # Gom theo cặp đầu mút (source, target) để xét Tầng 2 & Tầng 3 trong O(E)
        by_endpoints: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
        for edge in active_edges:
            s = str(edge.get("source", "")).strip()
            t = str(edge.get("target", "")).strip()
            nr = normal(str(edge.get("relation", "")).strip())
            by_endpoints.setdefault((s, t), {}).setdefault(nr, []).append(edge)

        # Tầng 2: Cùng cặp thực thể (source, target) nhưng vị từ tương đồng (Fuzzy / Keyword Overlap)
        if include_fuzzy_same_endpoints and eff_thresh < 1.0:
            for (s, t), rel_buckets in by_endpoints.items():
                if len(rel_buckets) < 2:
                    continue
                norm_rels = sorted(rel_buckets.keys())
                for i in range(len(norm_rels)):
                    for j in range(i + 1, len(norm_rels)):
                        nr1, nr2 = norm_rels[i], norm_rels[j]
                        c1 = nr1.replace("_", " ").strip()
                        c2 = nr2.replace("_", " ").strip()
                        sim_score, sim_reasons = score_text_pair_similarity(
                            c1,
                            c2,
                            fuzzy_threshold=eff_thresh,
                        )
                        w1 = set(c1.split()) - _PASSIVE_STOPWORDS
                        w2 = set(c2.split()) - _PASSIVE_STOPWORDS
                        if w1 and w2:
                            inter = len(w1 & w2)
                            union = len(w1 | w2)
                            if inter > 0 and union > 0:
                                jacc = round(inter / union, 2)
                                if jacc >= eff_thresh and jacc >= sim_score:
                                    sim_score = max(sim_score, jacc)
                                    sim_reasons.append(f"Chung {inter}/{union} từ khóa cốt lõi")

                        if sim_reasons and sim_score >= eff_thresh:
                            combined = rel_buckets[nr1] + rel_buckets[nr2]
                            sig = tuple(sorted(str(e.get("id", "")) for e in combined))
                            if sig in seen_edge_sets:
                                continue
                            seen_edge_sets.add(sig)
                            r1_disp = str(rel_buckets[nr1][0].get("relation", nr1))
                            r2_disp = str(rel_buckets[nr2][0].get("relation", nr2))
                            suggestions.append(
                                _build_triple_group_record(
                                    combined,
                                    nodes_by_id,
                                    match_type="fuzzy_relation",
                                    match_type_label="Cùng cặp nút · Vị từ tương đồng",
                                    score=min(0.99, sim_score),
                                    reason=f"Cùng cặp thực thể, vị từ tương đồng ('{r1_disp}' ↔ '{r2_disp}': {'; '.join(sim_reasons)})",
                                )
                            )

        # Tầng 3: Bộ ba đảo chiều Chủ động – Bị động giữa cùng 2 thực thể (u -> v vs v -> u)
        if include_inverse_pairs and eff_thresh < 1.0:
            visited_unordered: set[tuple[str, str]] = set()
            for (u, v), rels_uv in by_endpoints.items():
                if u == v:
                    continue
                pair_uv = (min(u, v), max(u, v))
                if pair_uv in visited_unordered or (v, u) not in by_endpoints:
                    continue
                visited_unordered.add(pair_uv)
                rels_vu = by_endpoints[(v, u)]

                for nr_uv, edges_uv in rels_uv.items():
                    c_uv = nr_uv.replace("_", " ").strip()
                    uv_passive = c_uv.startswith(_PASSIVE_MARKERS) or " bởi" in c_uv or " boi" in c_uv
                    w_uv = set(c_uv.split()) - _PASSIVE_STOPWORDS
                    if not w_uv:
                        continue
                    for nr_vu, edges_vu in rels_vu.items():
                        c_vu = nr_vu.replace("_", " ").strip()
                        vu_passive = c_vu.startswith(_PASSIVE_MARKERS) or " bởi" in c_vu or " boi" in c_vu
                        if uv_passive == vu_passive:
                            continue
                        w_vu = set(c_vu.split()) - _PASSIVE_STOPWORDS
                        if not w_vu:
                            continue
                        inter = len(w_uv & w_vu)
                        union = len(w_uv | w_vu)
                        core_jacc = inter / union if union else 0.0
                        core_str_1 = " ".join(sorted(w_uv))
                        core_str_2 = " ".join(sorted(w_vu))
                        core_sim, _ = score_text_pair_similarity(core_str_1, core_str_2, fuzzy_threshold=eff_thresh)
                        inv_score = round(max(core_jacc, core_sim * 0.92), 2)
                        if inv_score >= max(0.65, eff_thresh):
                            combined = edges_uv + edges_vu
                            sig = tuple(sorted(str(e.get("id", "")) for e in combined))
                            if sig in seen_edge_sets:
                                continue
                            seen_edge_sets.add(sig)
                            active_edges_side = edges_vu if uv_passive else edges_uv
                            best_active = rank_representative_edge(active_edges_side)
                            r_uv_disp = str(edges_uv[0].get("relation", nr_uv))
                            r_vu_disp = str(edges_vu[0].get("relation", nr_vu))
                            suggestions.append(
                                _build_triple_group_record(
                                    combined,
                                    nodes_by_id,
                                    match_type="inverse_pair",
                                    match_type_label="Đảo chiều Chủ động/Bị động",
                                    score=min(0.95, inv_score),
                                    reason=f"Đảo chiều Chủ động – Bị động ('{r_uv_disp}' ↔ '{r_vu_disp}')",
                                    canonical_relation=str(best_active.get("relation", "")),
                                    preferred_rep_id=str(best_active.get("id", "")),
                                )
                            )

        suggestions.sort(key=lambda x: (-float(x["score"]), -int(x["count"])))
        if len(_TRIPLE_DUPLICATE_SUGGESTIONS_CACHE) > 32:
            _TRIPLE_DUPLICATE_SUGGESTIONS_CACHE.clear()
        _TRIPLE_DUPLICATE_SUGGESTIONS_CACHE[cache_key] = suggestions

    all_suggestions = [copy.deepcopy(g) for g in _TRIPLE_DUPLICATE_SUGGESTIONS_CACHE[cache_key]]
    dismissed_records = project.get("not_duplicate_edge_pairs", [])
    filtered = filter_dismissed_pairs(
        all_suggestions,
        dismissed_records,
        id_a_key="edge_a_id",
        id_b_key="edge_b_id",
        fp_key="",
        include_dismissed=include_dismissed,
        use_normal=False,
    )
    if include_dismissed or not dismissed_records:
        return filtered

    # Kiểm tra bổ sung nếu mọi cặp cạnh thành phần trong nhóm đều đã được đánh dấu miễn trừ
    dismissed_pair_set = {
        normalize_pair_key(str(r.get("edge_a_id", "")), str(r.get("edge_b_id", "")), use_normal=False)
        for r in dismissed_records
        if r.get("edge_a_id") and r.get("edge_b_id")
    }
    final_list: list[dict[str, Any]] = []
    for g in filtered:
        eids = [str(eid) for eid in g.get("edge_ids", []) if eid]
        if len(eids) == 2 and normalize_pair_key(eids[0], eids[1], use_normal=False) in dismissed_pair_set:
            continue
        final_list.append(g)
    return final_list


def collapse_duplicate_edges(
    project: dict,
    *,
    selected_groups: list[dict[str, Any] | list[str]] | None = None,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, int, list[dict[str, Any]]]:
    """Hợp nhất thông minh các nhóm cạnh trùng bộ ba (toàn cục hoặc theo danh sách nhóm được chọn lọc).
    
    Bảo toàn 100% bằng chứng: dồn toàn bộ evidences của các cạnh trùng vào cạnh đại diện.
    Thu thập tất cả original_relations, tôn trọng danh sách miễn trừ not_duplicate_edge_pairs
    và cập nhật bảng ánh xạ edge_redirects.
    """
    candidate = _clone_project_for_merge_mutation(project)
    edges = candidate.get("edges", [])
    if not edges:
        return candidate, 0, []
    edge_idx_by_id = {str(e.get("id", "")): idx for idx, e in enumerate(edges)}

    dismissed_records = candidate.get("not_duplicate_edge_pairs", [])
    dismissed_pair_set = {
        normalize_pair_key(str(r.get("edge_a_id", "")), str(r.get("edge_b_id", "")), use_normal=False)
        for r in dismissed_records
        if r.get("edge_a_id") and r.get("edge_b_id")
    }

    work_groups: list[tuple[tuple[str, str, str], list[dict[str, Any]], str, str]] = []
    if selected_groups is not None:
        for sg in selected_groups:
            if isinstance(sg, dict):
                raw_eids = [str(eid).strip() for eid in sg.get("edge_ids", []) if str(eid).strip()]
                pref_rep_id = str(sg.get("representative_id") or sg.get("keep_edge_id") or "").strip()
                canon_rel = str(sg.get("canonical_relation") or sg.get("relation") or "").strip()
            elif isinstance(sg, (list, tuple)):
                raw_eids = [str(eid).strip() for eid in sg if str(eid).strip()]
                pref_rep_id = ""
                canon_rel = ""
            else:
                continue
            grp_edges = [
                edges[edge_idx_by_id[eid]]
                for eid in dict.fromkeys(raw_eids)
                if eid in edge_idx_by_id and edges[edge_idx_by_id[eid]].get("status") != STATUS_REJECTED
            ]
            if len(grp_edges) > 1:
                first_e = grp_edges[0]
                t_key = (
                    str(first_e.get("source", "")),
                    normal(canon_rel or str(first_e.get("relation", ""))),
                    str(first_e.get("target", "")),
                )
                work_groups.append((t_key, grp_edges, pref_rep_id, canon_rel))
    else:
        groups = group_edges_by_triplet(edges, exclude_rejected=True)
        for t_key, grp_edges in groups.items():
            if len(grp_edges) <= 1:
                continue
            sorted_ids = sorted(str(e.get("id", "")) for e in grp_edges if e.get("id"))
            if len(sorted_ids) >= 2:
                group_sig_key = normalize_pair_key(sorted_ids[0], "|".join(sorted_ids[1:]), use_normal=False)
                if group_sig_key in dismissed_pair_set:
                    continue
                if len(sorted_ids) == 2 and normalize_pair_key(sorted_ids[0], sorted_ids[1], use_normal=False) in dismissed_pair_set:
                    continue
            work_groups.append((t_key, grp_edges, "", ""))

    dropped_ids: set[str] = set()
    collapsed_records: list[dict[str, Any]] = []
    new_edge_redirects: dict[str, str] = {}

    for (s, r, t), raw_group, pref_rep_id, canon_rel in work_groups:
        group = [e for e in raw_group if str(e.get("id", "")) not in dropped_ids]
        if len(group) <= 1:
            continue

        rep = next((e for e in group if str(e.get("id", "")) == pref_rep_id), None) or rank_representative_edge(group)
        rep_id = str(rep["id"])
        rep_idx = edge_idx_by_id[rep_id]

        dups = [e for e in group if str(e.get("id")) != rep_id]
        if not dups:
            continue

        rep_copy = dict(candidate["edges"][rep_idx])
        rep_copy["evidences"] = consolidate_edge_evidences(rep_copy, dups)

        all_orig_rels = list(rep_copy.get("original_relations") or [])
        curr_rel = str(rep_copy.get("relation", "")).strip()
        if canon_rel and canon_rel != curr_rel:
            rep_copy["original_relation"] = rep_copy.get("original_relation") or curr_rel
            rep_copy["relation"] = canon_rel
        if rep_copy.get("original_relation") and rep_copy["original_relation"] not in all_orig_rels:
            all_orig_rels.append(rep_copy["original_relation"])
        for d in dups:
            d_rel = str(d.get("relation", "")).strip()
            if d_rel and d_rel != str(rep_copy.get("relation", "")).strip() and d_rel not in all_orig_rels:
                all_orig_rels.append(d_rel)
            if d.get("original_relation") and d["original_relation"] not in all_orig_rels:
                all_orig_rels.append(d["original_relation"])
            for sub_r in d.get("original_relations", []):
                if sub_r not in all_orig_rels:
                    all_orig_rels.append(sub_r)
        rep_copy["original_relations"] = all_orig_rels

        all_pids = list(rep_copy.get("schema_proposal_ids") or [])
        for d in dups:
            for pid in d.get("schema_proposal_ids", []):
                if pid not in all_pids:
                    all_pids.append(pid)
        rep_copy["schema_proposal_ids"] = all_pids

        candidate["edges"][rep_idx] = rep_copy

        dup_ids = [str(d["id"]) for d in dups]
        for did in dup_ids:
            dropped_ids.add(did)
            new_edge_redirects[did] = rep_id

        collapsed_records.append(
            {
                "triplet": (s, r, t),
                "representative_id": rep_id,
                "dropped_ids": dup_ids,
                "count": len(dups),
            }
        )

    candidate["edge_redirects"] = update_redirect_map(
        candidate.get("edge_redirects", {}),
        new_edge_redirects,
    )
    candidate["edges"] = [e for e in candidate["edges"] if str(e.get("id")) not in dropped_ids]

    if dropped_ids:
        candidate.setdefault("curation_history", []).append(
            {
                "at": now_iso(),
                "actor": actor,
                "operation": "collapse_duplicate_edges",
                "dropped_edges_count": len(dropped_ids),
                "groups_count": len(collapsed_records),
                "note": note or f"Thu gọn {len(dropped_ids)} cạnh trùng bộ ba.",
            }
        )

    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)
    clear_relation_duplicate_suggestions_cache()

    return candidate, len(dropped_ids), collapsed_records


def _execute_relation_merge_core(
    project: dict,
    flat_map: dict[str, str],
    *,
    collapse_edges: bool = False,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
    operation: str = "bulk_relation_merge",
    source_relations: list[str] | None = None,
    target_relation: str = "",
) -> tuple[dict, CurationResultDTO]:
    """Lõi thực thi chung cho cả gộp đơn lẻ và gộp hàng loạt quan hệ."""
    candidate = _clone_project_for_merge_mutation(project)
    rev_before = compute_project_revision(candidate)
    batch_id = uid()
    request_id = uid()
    merge_time = now_iso()

    affected_edges: list[str] = []
    edges_list = candidate["edges"]
    for idx, edge in enumerate(edges_list):
        r = str(edge.get("relation", "")).strip()
        if r in flat_map:
            new_edge = dict(edge)
            new_edge["original_relation"] = new_edge.get("original_relation") or r
            new_edge["relation"] = flat_map[r]
            edges_list[idx] = new_edge
            affected_edges.append(str(new_edge["id"]))

    candidate["relation_redirects"] = update_redirect_map(
        candidate.get("relation_redirects", {}),
        flat_map,
    )

    aliases_map = candidate.setdefault("relation_aliases", {})
    for s, t in flat_map.items():
        t_aliases = list(aliases_map.get(t, []))
        if s not in t_aliases and normal(s) != normal(t):
            t_aliases.append(s)
        aliases_map[t] = t_aliases

    source_set = set(flat_map.keys())
    all_targets = set(flat_map.values())
    rel_types = candidate.setdefault("relation_types", [])
    candidate["relation_types"] = [
        r for r in rel_types if str(r.get("name", "")).strip() not in source_set
    ]
    raw_rels = candidate.setdefault("relations", [])
    candidate["relations"] = [r for r in raw_rels if r not in source_set]
    raw_rels_set = set(candidate["relations"])
    rel_notes = candidate.setdefault("relation_notes", {})
    for s in source_set:
        rel_notes.pop(s, None)

    rel_types_by_norm: dict[str, list[dict]] = {}
    for r in candidate["relation_types"]:
        rel_types_by_norm.setdefault(normal(r.get("name", "")), []).append(r)

    for t in all_targets:
        t_aliases = aliases_map.get(t, [])
        t_norm = normal(t)
        matched_rows = rel_types_by_norm.get(t_norm)
        if matched_rows:
            for r in matched_rows:
                curr_r_aliases = list(r.get("aliases") or [])
                curr_set = set(curr_r_aliases)
                for a in t_aliases:
                    if a not in curr_set and normal(a) != t_norm:
                        curr_r_aliases.append(a)
                        curr_set.add(a)
                r["aliases"] = curr_r_aliases
        else:
            sources_label = ", ".join(source_relations or flat_map.keys())
            new_rt = {
                "name": t,
                "description": f"Quan hệ chuẩn hóa sau gộp từ: {sources_label}",
                "definition": f"Quan hệ '{t}' gộp từ các biến thể.",
                "aliases": list(t_aliases),
            }
            candidate["relation_types"].append(new_rt)
            rel_types_by_norm.setdefault(t_norm, []).append(new_rt)
        rel_notes.setdefault(t, {})["aliases"] = list(t_aliases)
        if t not in raw_rels_set:
            candidate["relations"].append(t)
            raw_rels_set.add(t)

    props_list = candidate.get("schema_proposals", [])
    for idx, p in enumerate(props_list):
        p_name = p.get("name", "")
        if p.get("kind") == "relations" and p_name in flat_map:
            new_p = copy.deepcopy(p)
            new_p["status"] = "merged"
            new_p["canonical_name"] = flat_map[p_name]
            new_p["reviewed_at"] = merge_time
            new_p["review_note"] = (str(new_p.get("review_note") or "") + f" [Gộp vào '{flat_map[p_name]}']").strip()
            props_list[idx] = new_p

    merged_dup_count = 0
    if collapse_edges:
        _, merged_dup_count, _ = collapse_duplicate_edges(
            candidate,
            actor=actor,
            note=f"Tự động hợp nhất cạnh trùng sau khi gộp quan hệ",
            mutate_in_place=True,
        )

    if operation == "relation_merge" and source_relations:
        eff_target = target_relation or flat_map[source_relations[0]]
        merge_rec: dict[str, Any] = {
            "merge_id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": actor,
            "source_relations": source_relations,
            "target_relation": eff_target,
            "affected_edge_count": len(affected_edges),
            "merged_duplicate_edges": merged_dup_count,
            "aliases_stored": list(aliases_map.get(eff_target, [])),
            "note": note or f"Gộp quan hệ: {', '.join(source_relations)} → {eff_target}",
        }
    else:
        merge_rec = {
            "merge_id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": actor,
            "is_bulk": True,
            "merged_relations_count": len(flat_map),
            "affected_edge_count": len(affected_edges),
            "merged_duplicate_edges": merged_dup_count,
            "note": note or f"Gộp hàng loạt {len(flat_map)} quan hệ.",
        }
    candidate.setdefault("relation_merges", []).append(merge_rec)

    rev_after = compute_project_revision(candidate)
    applied_list = source_relations if (operation == "relation_merge" and source_relations) else list(flat_map.keys())
    item_results = [{"source": s, "target": flat_map[s]} for s in applied_list]
    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or project.get("name") or ""),
        operation=operation,
        status="applied",
        apply_mode="all_or_nothing",
        revision_before=rev_before,
        revision_after=rev_after,
        applied_ids=applied_list,
        skipped_ids=[],
        applied_count=len(applied_list),
        skipped_count=0,
        item_results=item_results,
        affected_edge_ids=affected_edges,
        merged_duplicate_edges=merged_dup_count,
    )

    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)
    clear_duplicate_suggestions_cache()
    clear_relation_duplicate_suggestions_cache()
    return candidate, result


def apply_relation_merge(
    project: dict,
    source_relations: list[str],
    target_relation: str,
    *,
    collapse_edges: bool = False,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Gộp một hoặc nhiều quan hệ nguồn về 1 quan hệ đích duy nhất."""
    target_clean = str(target_relation or "").strip()
    if not target_clean:
        raise ValueError("Quan hệ đích không được rỗng.")

    sources = [str(r).strip() for r in source_relations if str(r).strip() and str(r).strip() != target_clean]
    if not sources:
        raise ValueError("Cần ít nhất một quan hệ nguồn khác quan hệ đích để thực hiện gộp.")

    flat_map = {s: target_clean for s in sources}
    return _execute_relation_merge_core(
        project,
        flat_map,
        collapse_edges=collapse_edges,
        actor=actor,
        note=note,
        mutate_in_place=mutate_in_place,
        operation="relation_merge",
        source_relations=sources,
        target_relation=target_clean,
    )


def bulk_apply_relation_merges(
    project: dict,
    mappings: list[dict | tuple[str, str]] | dict[str, str],
    *,
    collapse_edges: bool = False,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Gộp hàng loạt nhiều cặp quan hệ nghi trùng cùng lúc.
    Mỗi phần tử trong mappings là (source_relation, target_relation) hoặc {'source': ..., 'target': ...} hoặc mapping dict.
    """
    if not mappings:
        raise ValueError("Danh sách quan hệ cần gộp trống.")

    resolved_pairs: list[tuple[str, str]] = []
    items_to_process = list(mappings.items()) if isinstance(mappings, dict) else mappings
    for item in items_to_process:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            s, t = str(item[0]).strip(), str(item[1]).strip()
        elif isinstance(item, dict):
            s = str(item.get("source") or item.get("source_relation") or "").strip()
            t = str(item.get("target") or item.get("target_relation") or "").strip()
        else:
            continue
        if s and t and s != t:
            resolved_pairs.append((s, t))

    if not resolved_pairs:
        raise ValueError("Không có cặp quan hệ hợp lệ để gộp.")

    flat_map = flatten_redirects(resolved_pairs)
    return _execute_relation_merge_core(
        project,
        flat_map,
        collapse_edges=collapse_edges,
        actor=actor,
        note=note,
        mutate_in_place=mutate_in_place,
        operation="bulk_relation_merge",
    )


def mark_relation_pair_not_duplicate(project: dict, rel_a: str, rel_b: str, note: str = "") -> dict:
    """Đánh dấu hai quan hệ là khác nhau để không gợi ý lại."""
    a = str(rel_a or "").strip()
    b = str(rel_b or "").strip()
    if not a or not b or a == b:
        raise ValueError("Cặp quan hệ không hợp lệ")
    mark_relation_pairs_not_duplicate_bulk(project, [(a, b)], note=note)
    return {
        "ok": True,
        "entry": {
            "relation_a": min(a, b),
            "relation_b": max(a, b),
            "at": now_iso(),
            "note": note.strip(),
        },
    }


def mark_relation_pairs_not_duplicate_bulk(
    project: dict,
    pairs: list[tuple[str, str] | list[str] | dict[str, Any]],
    note: str = "",
) -> dict[str, Any]:
    """Đánh dấu hàng loạt cặp quan hệ là khác nhau trong một lần quét O(R + K)."""
    existing_list = project.setdefault("not_duplicate_relation_pairs", [])
    seen_keys = {
        normalize_pair_key(str(p.get("relation_a", "")), str(p.get("relation_b", "")))
        for p in existing_list
    }
    ts = now_iso()
    clean_note = str(note or "").strip()
    added = 0
    for item in pairs:
        if isinstance(item, dict):
            a = str(item.get("relation_a") or item.get("source") or "").strip()
            b = str(item.get("relation_b") or item.get("target") or "").strip()
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            a, b = str(item[0]).strip(), str(item[1]).strip()
        else:
            continue
        if not a or not b or a == b:
            continue
        key = normalize_pair_key(a, b)
        if key not in seen_keys:
            seen_keys.add(key)
            existing_list.append(
                {
                    "relation_a": min(a, b),
                    "relation_b": max(a, b),
                    "at": ts,
                    "note": clean_note,
                }
            )
            added += 1
    clear_relation_duplicate_suggestions_cache()
    return {"ok": True, "added_count": added}


def mark_edge_groups_not_duplicate_bulk(
    project: dict,
    groups: list[dict[str, Any] | tuple[str, str] | list[str]],
    note: str = "",
    actor: str = "human_reviewer",
) -> dict[str, Any]:
    """Đánh dấu hàng loạt nhóm/cặp cạnh là Sự kiện Độc lập (Không gộp) vào not_duplicate_edge_pairs."""
    existing_list = project.setdefault("not_duplicate_edge_pairs", [])
    seen_keys = {
        normalize_pair_key(str(p.get("edge_a_id", "")), str(p.get("edge_b_id", "")), use_normal=False)
        for p in existing_list
        if p.get("edge_a_id") and p.get("edge_b_id")
    }
    ts = now_iso()
    clean_note = str(note or "Sự kiện độc lập (giữ riêng, không gộp)").strip()
    history = project.setdefault("curation_history", [])
    added = 0

    def _add_pair(id_a: str, id_b: str) -> None:
        nonlocal added
        if not id_a or not id_b or id_a == id_b:
            return
        pk = normalize_pair_key(id_a, id_b, use_normal=False)
        if pk not in seen_keys:
            seen_keys.add(pk)
            entry = {
                "id": uid(),
                "edge_a_id": pk[0],
                "edge_b_id": pk[1],
                "at": ts,
                "actor": actor,
                "note": clean_note,
            }
            existing_list.append(entry)
            history.append(
                {
                    "id": entry["id"],
                    "at": ts,
                    "actor": actor,
                    "decision_origin": "human",
                    "action": "mark_edge_group_not_duplicate",
                    "target_id": f"{pk[0]}:{pk[1]}",
                    "note": clean_note,
                    "before": None,
                    "after": entry,
                }
            )
            added += 1

    for item in groups:
        if isinstance(item, dict):
            ea = str(item.get("edge_a_id") or "").strip()
            eb = str(item.get("edge_b_id") or "").strip()
            eids = sorted(str(eid).strip() for eid in item.get("edge_ids", []) if str(eid).strip())
            if ea and eb:
                _add_pair(ea, eb)
            elif len(eids) >= 2:
                _add_pair(eids[0], "|".join(eids[1:]))
            if len(eids) == 2:
                _add_pair(eids[0], eids[1])
        elif isinstance(item, (tuple, list)):
            clean_ids = sorted(str(x).strip() for x in item if str(x).strip())
            if len(clean_ids) >= 2:
                _add_pair(clean_ids[0], "|".join(clean_ids[1:]))
                if len(clean_ids) == 2:
                    _add_pair(clean_ids[0], clean_ids[1])

    clear_relation_duplicate_suggestions_cache()
    return {"ok": True, "added_count": added}
