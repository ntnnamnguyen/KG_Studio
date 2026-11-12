"""Các hàm tiện ích và cấu trúc thuật toán dùng chung cho Gộp Thực thể, Quan hệ và Thu gọn Bộ ba."""
from __future__ import annotations

import copy
from difflib import SequenceMatcher
from typing import Any

from shared.constants import (
    STATUS_APPROVED,
    STATUS_CHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from shared.text_utils import normal, now_iso, uid


class DisjointSetUnion:
    """Cấu trúc dữ liệu Disjoint Set Union (DSU / Union-Find) với Path Compression tối ưu O(alpha(N))."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, i: str) -> str:
        if self.parent.setdefault(i, i) == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: str, j: str) -> None:
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j

    def get_clusters(self, items: list[str]) -> dict[str, list[str]]:
        clusters: dict[str, list[str]] = {}
        for item in items:
            root = self.find(item)
            clusters.setdefault(root, []).append(item)
        return clusters


def flatten_redirects(mapping: dict[str, str] | list[tuple[str, str]]) -> dict[str, str]:
    """Khử chuỗi chuyển hướng nhiều bậc (A -> B -> C => A -> C) và bảo vệ chống vòng lặp."""
    parent: dict[str, str] = {}
    if isinstance(mapping, dict):
        parent = dict(mapping)
    elif isinstance(mapping, list):
        for item in mapping:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                s, t = str(item[0]).strip(), str(item[1]).strip()
                if s and t and s != t:
                    parent[s] = t

    flat: dict[str, str] = {}
    for start in parent:
        curr = start
        visited: set[str] = set()
        while curr in parent and curr not in visited:
            visited.add(curr)
            curr = parent[curr]
        flat[start] = curr
    return flat


def update_redirect_map(
    existing: dict[str, str],
    new_mapping: dict[str, str],
    keep_id: str | None = None,
) -> dict[str, str]:
    """Cập nhật và làm phẳng bảng ánh xạ chuyển hướng (redirects), khử chuỗi đa bậc và vòng lặp."""
    redirects = dict(existing or {})
    for old_src, old_tgt in list(redirects.items()):
        if old_tgt in new_mapping:
            redirects[old_src] = new_mapping[old_tgt]
    for src, tgt in new_mapping.items():
        if src != tgt:
            redirects[src] = tgt
    if keep_id:
        redirects.pop(keep_id, None)
    return flatten_redirects(redirects)


def normalize_pair_key(a: str, b: str, use_normal: bool = True) -> tuple[str, str]:
    """Chuẩn hóa khóa của một cặp đối xứng (A, B) == (B, A)."""
    val_a = normal(str(a or "")) if use_normal else str(a or "").strip()
    val_b = normal(str(b or "")) if use_normal else str(b or "").strip()
    return (val_a, val_b) if val_a <= val_b else (val_b, val_a)


def generate_candidate_index_pairs(
    norm_names: list[str],
    norm_aliases: list[set[str]] | None = None,
    *,
    fuzzy_threshold: float = 0.0,
    force_all_threshold: int = 80,
    max_bucket_size: int = 60,
) -> set[tuple[int, int]]:
    """Gom các cặp chỉ số ứng viên nghi trùng lặp dựa trên Inverted Index & Token Blocking O(N log N)."""
    n_items = len(norm_names)
    candidate_pairs: set[tuple[int, int]] = set()

    def _add_pair(a_idx: int, b_idx: int) -> None:
        if a_idx != b_idx:
            candidate_pairs.add((min(a_idx, b_idx), max(a_idx, b_idx)))

    if n_items < force_all_threshold:
        for i in range(n_items):
            for j in range(i + 1, n_items):
                _add_pair(i, j)
        return candidate_pairs

    name_to_indices: dict[str, list[int]] = {}
    alias_to_indices: dict[str, list[int]] = {}
    token_to_indices: dict[str, list[int]] = {}
    prefix_to_indices: dict[str, list[int]] = {}

    aliases_list = norm_aliases or [set() for _ in range(n_items)]

    for idx, n_name in enumerate(norm_names):
        if n_name:
            name_to_indices.setdefault(n_name, []).append(idx)
            if len(n_name) >= 3:
                prefix_to_indices.setdefault(n_name[:3], []).append(idx)
            for tok in set(n_name.split()):
                if len(tok) >= 3:
                    token_to_indices.setdefault(tok, []).append(idx)
        if idx < len(aliases_list):
            for a_name in aliases_list[idx]:
                if a_name:
                    alias_to_indices.setdefault(a_name, []).append(idx)

    # 1. Khớp tên chuẩn hóa
    for idx_list in name_to_indices.values():
        if len(idx_list) > 1:
            for i_pos in range(len(idx_list)):
                for j_pos in range(i_pos + 1, len(idx_list)):
                    _add_pair(idx_list[i_pos], idx_list[j_pos])

    # 2. Khớp bí danh
    for a_name, a_indices in alias_to_indices.items():
        if a_name in name_to_indices:
            for n_idx in name_to_indices[a_name]:
                for a_idx in a_indices:
                    _add_pair(n_idx, a_idx)
        if len(a_indices) > 1:
            for i_pos in range(len(a_indices)):
                for j_pos in range(i_pos + 1, len(a_indices)):
                    _add_pair(a_indices[i_pos], a_indices[j_pos])

    # 3. Token & Prefix Blocking khi bật fuzzy
    if fuzzy_threshold:
        for tok, tok_indices in token_to_indices.items():
            if 1 < len(tok_indices) <= max_bucket_size:
                for i_pos in range(len(tok_indices)):
                    for j_pos in range(i_pos + 1, len(tok_indices)):
                        _add_pair(tok_indices[i_pos], tok_indices[j_pos])
        for pref, pref_indices in prefix_to_indices.items():
            if 1 < len(pref_indices) <= max_bucket_size:
                for i_pos in range(len(pref_indices)):
                    for j_pos in range(i_pos + 1, len(pref_indices)):
                        _add_pair(pref_indices[i_pos], pref_indices[j_pos])

    return candidate_pairs


def score_text_pair_similarity(
    name_a: str,
    name_b: str,
    aliases_a: set[str] | None = None,
    aliases_b: set[str] | None = None,
    *,
    fuzzy_threshold: float = 0.0,
) -> tuple[float, list[str]]:
    """Tính điểm tương đồng (0.0..1.0) và trích xuất danh sách lý do trùng lặp giữa 2 tên/bí danh."""
    a_set = aliases_a or set()
    b_set = aliases_b or set()
    reasons: list[str] = []

    if name_a and name_a == name_b:
        reasons.append("Trùng tên chuẩn hóa")
    if name_b in a_set or name_a in b_set:
        reasons.append("Tên này là bí danh của tên kia")
    if a_set & b_set:
        reasons.append("Có bí danh chung")

    len_a, len_b = len(name_a), len(name_b)
    max_len = max(len_a, len_b)
    score = 0.0
    if max_len > 0 and (abs(len_a - len_b) <= max_len * (1.0 - fuzzy_threshold + 0.05) or reasons):
        sm = SequenceMatcher(None, name_a, name_b)
        if reasons:
            score = sm.ratio()
        elif fuzzy_threshold and sm.real_quick_ratio() >= fuzzy_threshold and sm.quick_ratio() >= fuzzy_threshold:
            score = sm.ratio()
            if score >= fuzzy_threshold:
                reasons.append(f"Độ giống tên cao ({score:.2f})")

    return round(score, 2), reasons


def filter_dismissed_pairs(
    pairs: list[dict[str, Any]],
    dismissed_records: list[dict[str, Any]],
    *,
    id_a_key: str = "keep_id",
    id_b_key: str = "drop_id",
    fp_key: str = "pair_fingerprint",
    include_dismissed: bool = False,
    use_normal: bool = False,
) -> list[dict[str, Any]]:
    """Lọc bỏ các cặp đã được chuyên viên đánh dấu 'Khác đối tượng' (Blacklist)."""
    dismissed_map: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in dismissed_records:
        k = normalize_pair_key(
            str(rec.get("node_a_id") or rec.get("relation_a") or ""),
            str(rec.get("node_b_id") or rec.get("relation_b") or ""),
            use_normal=use_normal,
        )
        dismissed_map[k] = rec

    filtered: list[dict[str, Any]] = []
    for p in pairs:
        ida = str(p.get(id_a_key, "")).strip()
        idb = str(p.get(id_b_key, "")).strip()
        if not ida or not idb or ida == idb:
            continue
        k = normalize_pair_key(ida, idb, use_normal=use_normal)
        dis = dismissed_map.get(k)
        is_dismissed = bool(dis and (not fp_key or not dis.get(fp_key) or dis.get(fp_key) == p.get(fp_key)))
        p["dismissed"] = is_dismissed
        p["dismissed_note"] = str(dis.get("note", "")) if is_dismissed and dis else ""
        if is_dismissed and not include_dismissed:
            continue
        filtered.append(p)
    return filtered


def group_edges_by_triplet(
    edges: list[dict[str, Any]],
    *,
    exclude_rejected: bool = True,
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Gom nhóm danh sách cạnh theo bộ ba (source, normal(relation), target)."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for edge in edges:
        if exclude_rejected and edge.get("status") == STATUS_REJECTED:
            continue
        s = str(edge.get("source", "")).strip()
        r = normal(str(edge.get("relation", "")).strip())
        t = str(edge.get("target", "")).strip()
        if s and r and t:
            groups.setdefault((s, r, t), []).append(edge)
    return groups


def consolidate_edge_evidences(
    primary_edge: dict[str, Any],
    duplicate_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dồn toàn bộ danh sách bằng chứng (evidences, chunks, quotes) của các cạnh trùng vào cạnh đại diện."""
    def _extract_item(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "edge_id": str(e.get("id", "")),
            "doc_id": e.get("doc_id", ""),
            "doc_name": e.get("doc_name", ""),
            "chunk_number": int(e.get("chunk_number", 0) or 0),
            "start_char": e.get("start_char"),
            "end_char": e.get("end_char"),
            "evidence": e.get("evidence", ""),
            "status": e.get("status", ""),
            "original_relation": e.get("original_relation") or e.get("relation", ""),
        }

    kept_evs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _add(ev: dict[str, Any]) -> None:
        eid = str(ev.get("edge_id", ""))
        if eid and eid in seen_ids:
            return
        if eid:
            seen_ids.add(eid)
        kept_evs.append(ev)

    if isinstance(primary_edge.get("evidences"), list) and primary_edge["evidences"]:
        for dev in primary_edge["evidences"]:
            _add(dev)
    else:
        _add(_extract_item(primary_edge))

    for dup in duplicate_edges:
        if isinstance(dup.get("evidences"), list) and dup["evidences"]:
            for dev in dup["evidences"]:
                _add(dev)
        else:
            _add(_extract_item(dup))

    return kept_evs


def sort_edges_by_priority(edges_in_group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sắp xếp các cạnh theo thứ tự ưu tiên: Approved > Check > Pending, ưu tiên độ dài evidence."""
    status_rank = {
        STATUS_APPROVED: 3,
        STATUS_CHECK: 2,
        STATUS_PENDING: 1,
    }

    def _rank(item: dict) -> tuple[int, int]:
        st = status_rank.get(item.get("status"), 0)
        ev_len = len(str(item.get("evidence", "")))
        return (st, ev_len)

    return sorted(edges_in_group, key=_rank, reverse=True)


def rank_representative_edge(edges_in_group: list[dict[str, Any]]) -> dict[str, Any]:
    """Chọn cạnh đại diện tốt nhất trong nhóm cạnh trùng: Đã duyệt > Cần kiểm tra > Chờ duyệt, ưu tiên bằng chứng dài hơn."""
    return sort_edges_by_priority(edges_in_group)[0]


def _clone_project_for_merge_mutation(project: dict) -> dict:
    """Tạo bản sao nông có chọn lọc để tối ưu hiệu năng O(V+E) khi gộp thực thể và quan hệ."""
    candidate = dict(project)
    candidate["nodes"] = [copy.copy(n) for n in project.get("nodes", [])]
    candidate["edges"] = [copy.copy(e) for e in project.get("edges", [])]
    candidate["entity_merges"] = list(project.get("entity_merges", []))
    candidate["relation_merges"] = list(project.get("relation_merges", []))
    candidate["node_redirects"] = dict(project.get("node_redirects", {}))
    candidate["relation_redirects"] = dict(project.get("relation_redirects", {}))
    candidate["edge_redirects"] = dict(project.get("edge_redirects", {}))
    candidate["curation_history"] = list(project.get("curation_history", []))
    return candidate


def consolidate_node_attributes(
    target_node: dict[str, Any],
    absorbed_nodes: list[dict[str, Any]],
    *,
    merge_time: str,
    batch_id: str = "",
) -> dict[str, Any]:
    """Gom toàn bộ aliases, documents, schema_proposal_ids, edc_observations và lịch sử merged_from từ các node bị gộp."""
    from .common import clean_aliases

    raw_aliases: list[str] = list(target_node.get("aliases") or [])
    merged_docs: list[str] = list(target_node.get("documents") or [])
    merged_props: list[str] = list(target_node.get("schema_proposal_ids") or [])
    merged_obs: list[dict[str, Any]] = copy.deepcopy(list(target_node.get("edc_observations") or []))
    merged_from: list[dict[str, Any]] = list(target_node.get("merged_from") or [])

    target_name = str(target_node.get("name", ""))

    for d_node in absorbed_nodes:
        d_id = str(d_node.get("id", ""))
        d_name = str(d_node.get("name", ""))
        if d_name:
            raw_aliases.append(d_name)
        raw_aliases.extend(str(a) for a in d_node.get("aliases", []))
        for doc_id in d_node.get("documents", []):
            if doc_id and doc_id not in merged_docs:
                merged_docs.append(doc_id)
        for p_id in d_node.get("schema_proposal_ids", []):
            if p_id and p_id not in merged_props:
                merged_props.append(p_id)
        for obs in d_node.get("edc_observations", []):
            if obs not in merged_obs:
                merged_obs.append(copy.deepcopy(obs))
        entry: dict[str, Any] = {
            "id": d_id,
            "name": d_name,
            "kind": d_node.get("kind", ""),
            "description": d_node.get("description", ""),
            "aliases": list(d_node.get("aliases", [])),
            "documents": list(d_node.get("documents", [])),
            "at": merge_time,
        }
        if batch_id:
            entry["batch_id"] = batch_id
        merged_from.append(entry)

    target_node["aliases"] = clean_aliases(raw_aliases, target_name)
    target_node["documents"] = merged_docs
    target_node["schema_proposal_ids"] = list(dict.fromkeys(merged_props))
    target_node["edc_observations"] = merged_obs
    target_node["merged_from"] = merged_from
    return target_node


def remap_graph_edges_endpoints(
    edges: list[dict[str, Any]],
    drop_to_keep: dict[str, str],
    *,
    member_set: set[str] | None = None,
    kind_changed_by_member: dict[str, bool] | None = None,
    merge_time: str = "",
    actor: str = "",
    keep_id: str = "",
    curation_history: list[dict[str, Any]] | None = None,
    simulate_only: bool = False,
) -> tuple[list[str], int, list[str], int, list[dict[str, Any]], list[dict[str, Any]]]:
    """Cập nhật hoặc mô phỏng đầu mút cạnh khi gộp thực thể.
    
    Returns:
        (affected_edge_ids, changed_endpoints, new_self_loop_ids, invalidated_approved_count, edge_changes, resulting_edges)
    """
    affected_edge_ids: list[str] = []
    changed_endpoints = 0
    invalidated_approved_count = 0
    new_self_loop_ids: list[str] = []
    edge_changes: list[dict[str, Any]] = []
    resulting_edges: list[dict[str, Any]] = []

    m_set = member_set or set()
    kc_map = kind_changed_by_member or {}
    ts = merge_time or now_iso()

    for idx, raw_edge in enumerate(edges):
        edge = copy.deepcopy(raw_edge) if simulate_only else raw_edge
        old_src = str(edge.get("source", ""))
        old_tgt = str(edge.get("target", ""))
        was_self = old_src == old_tgt
        src_changed = old_src in drop_to_keep
        tgt_changed = old_tgt in drop_to_keep
        endpoint_kind_changed = (old_src in m_set and kc_map.get(old_src, False)) or (
            old_tgt in m_set and kc_map.get(old_tgt, False)
        )

        if not (src_changed or tgt_changed or endpoint_kind_changed):
            if simulate_only:
                resulting_edges.append(edge)
            continue

        before_edge = copy.deepcopy(edge)
        eid = str(edge.get("id", ""))
        if src_changed or tgt_changed:
            affected_edge_ids.append(eid)
            changed_endpoints += (1 if src_changed else 0) + (1 if tgt_changed else 0)

        new_src = drop_to_keep[old_src] if src_changed else old_src
        new_tgt = drop_to_keep[old_tgt] if tgt_changed else old_tgt

        became_self_loop = (new_src == new_tgt) and not was_self
        if became_self_loop:
            new_self_loop_ids.append(eid)

        old_status = str(edge.get("status", STATUS_PENDING))
        if old_status == STATUS_REJECTED:
            new_status = STATUS_REJECTED
        elif became_self_loop or endpoint_kind_changed:
            new_status = STATUS_CHECK
            if old_status == STATUS_APPROVED:
                invalidated_approved_count += 1
        else:
            new_status = old_status

        if not simulate_only:
            edge.setdefault("endpoint_history", []).append(
                {
                    "at": ts,
                    "source_before": old_src,
                    "target_before": old_tgt,
                    "status_before": old_status,
                    "reviewed_at_before": edge.get("reviewed_at", ""),
                    "override_before": bool(edge.get("override", False)),
                }
            )
            edge["source"] = new_src
            edge["target"] = new_tgt

            if became_self_loop:
                edge["self_loop_after_merge"] = True
                edge["self_loop_confirmed"] = False
                self_note = f"[Cần kiểm tra: Tự nối phát sinh sau khi gộp thực thể vào {keep_id or new_src}]"
                if self_note not in str(edge.get("review_note", "")):
                    edge["review_note"] = (str(edge.get("review_note", "")) + "\n" + self_note).strip()

            if (became_self_loop or endpoint_kind_changed) and old_status != STATUS_REJECTED:
                edge["status"] = STATUS_CHECK
                edge["reviewed_at"] = ""
                edge["override"] = False
                edge["override_reason"] = ""

            if curation_history is not None:
                curation_history.append(
                    {
                        "id": uid(),
                        "at": ts,
                        "actor": actor,
                        "decision_origin": "human",
                        "action": "edge_endpoint_remapped_by_merge",
                        "target_id": eid,
                        "before": before_edge,
                        "after": copy.deepcopy(edge),
                        "note": f"Đổi đầu mút do gộp thực thể vào {keep_id or new_src}",
                    }
                )
        else:
            edge["source"] = new_src
            edge["target"] = new_tgt
            edge["status"] = new_status
            edge_changes.append(
                {
                    "edge_id": eid,
                    "relation": str(edge.get("relation", "")),
                    "source_before": old_src,
                    "target_before": old_tgt,
                    "source_after": new_src,
                    "target_after": new_tgt,
                    "endpoints_changed": (1 if src_changed else 0) + (1 if tgt_changed else 0),
                    "status_before": old_status,
                    "status_after": new_status,
                    "became_self_loop": became_self_loop,
                    "endpoint_kind_changed": endpoint_kind_changed,
                    "evidence": str(edge.get("evidence", "")),
                }
            )

        if simulate_only:
            resulting_edges.append(edge)

    return (
        affected_edge_ids,
        changed_endpoints,
        new_self_loop_ids,
        invalidated_approved_count,
        edge_changes,
        resulting_edges,
    )
