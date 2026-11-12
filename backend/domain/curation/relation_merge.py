"""Các thuật toán và thao tác Gộp Quan hệ (Relation Merge), Thu gọn Cạnh trùng (Collapse Edges) và Quản lý Cặp nghi trùng."""
from __future__ import annotations

from collections import Counter
import copy
from difflib import SequenceMatcher
from typing import Any

from backend.domain.catalogs.service import compute_project_revision
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
    update_redirect_map,
)

# Bộ nhớ đệm gợi ý quan hệ nghi trùng theo (project_id, revision, fuzzy_threshold)
_RELATION_DUPLICATE_SUGGESTIONS_CACHE: dict[tuple[str, str, float], list[dict[str, Any]]] = {}


def clear_relation_duplicate_suggestions_cache() -> None:
    """Xóa toàn bộ bộ nhớ đệm gợi ý trùng lặp quan hệ."""
    _RELATION_DUPLICATE_SUGGESTIONS_CACHE.clear()


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


def collapse_duplicate_edges(
    project: dict,
    *,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, int, list[dict[str, Any]]]:
    """Hợp nhất thông minh các cạnh có cùng bộ ba (source, normal(relation), target).
    
    Bảo toàn 100% bằng chứng: dồn toàn bộ evidences của các cạnh trùng vào cạnh đại diện.
    Thu thập tất cả original_relations và cập nhật bảng ánh xạ edge_redirects.
    """
    candidate = _clone_project_for_merge_mutation(project)
    edges = candidate.get("edges", [])
    if not edges:
        return candidate, 0, []
    edge_idx_by_id = {str(e.get("id", "")): idx for idx, e in enumerate(edges)}

    groups = group_edges_by_triplet(edges, exclude_rejected=True)

    dropped_ids: set[str] = set()
    collapsed_records: list[dict[str, Any]] = []
    new_edge_redirects: dict[str, str] = {}

    for (s, r, t), group in groups.items():
        if len(group) <= 1:
            continue

        rep = rank_representative_edge(group)
        rep_id = str(rep["id"])
        rep_idx = edge_idx_by_id[rep_id]

        dups = [e for e in group if str(e.get("id")) != rep_id]
        if not dups:
            continue

        rep_copy = dict(candidate["edges"][rep_idx])
        rep_copy["evidences"] = consolidate_edge_evidences(rep_copy, dups)

        all_orig_rels = list(rep_copy.get("original_relations") or [])
        if rep_copy.get("original_relation") and rep_copy["original_relation"] not in all_orig_rels:
            all_orig_rels.append(rep_copy["original_relation"])
        for d in dups:
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
