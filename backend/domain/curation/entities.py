"""Quản lý hồ sơ thực thể, bậc liên kết, gợi ý trùng lặp và thống kê đồ thị."""
from __future__ import annotations

import copy
from difflib import SequenceMatcher
import json
from typing import Any

from backend.domain.catalogs.service import (
    catalog_rows,
    compute_project_revision,
)
from backend.domain.documents.processor import count_chunks
from shared.constants import (
    STATUS_APPROVED,
    STATUS_CHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from shared.text_utils import normal, now_iso, sha, uid

from .common import clean_aliases, clean_display_text, find_node
from .validation import inspect_edge_schema_status

# Bộ nhớ đệm gợi ý trùng lặp theo (project_id, revision, fuzzy_threshold) tránh tính lại O(n^2) mỗi lần rerun
_DUPLICATE_SUGGESTIONS_CACHE: dict[tuple[str, str, float], list[dict[str, Any]]] = {}


def update_node(project: dict, node_id: str, **fields) -> dict:
    """Cập nhật hồ sơ thực thể theo đúng Ma trận ảnh hưởng mục 8.2:
    - Sửa tên hiển thị, bí danh hoặc mô tả (không đổi loại) -> giữ ID, lưu audit, KHÔNG tự thay đổi trạng thái cạnh.
    - Đổi loại node (chỉ cho phép chọn từ catalog đã duyệt) -> các cạnh nối node chuyển về Cần kiểm tra (trừ cạnh Loại bỏ).
    """
    node = find_node(project, node_id)
    if not node:
        raise ValueError("Không tìm thấy thực thể")

    before_node = copy.deepcopy(node)
    kind_changed = False

    if "name" in fields and fields["name"] is not None:
        name = clean_display_text(str(fields["name"]))
        if not name:
            raise ValueError("Tên thực thể không được rỗng")
        node["name"] = name

    if "kind" in fields and fields["kind"] is not None:
        new_kind = clean_display_text(str(fields["kind"]))
        if not new_kind:
            raise ValueError("Loại thực thể không được rỗng")
        if normal(new_kind) != normal(str(node.get("kind", ""))):
            approved_types = {normal(t["name"]): t["name"] for t in catalog_rows(project, "entity_types")}
            if normal(new_kind) not in approved_types:
                raise ValueError(
                    f"Loại thực thể '{new_kind}' chưa có trong danh mục đã duyệt. Nếu cần loại mới, hãy dùng luồng đề xuất ở Trang 4."
                )
            node["kind"] = approved_types[normal(new_kind)]
            proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
            node["schema_proposal_ids"] = [
                pid for pid in node.get("schema_proposal_ids", [])
                if proposals_by_id.get(str(pid), {}).get("kind") != "entity_types"
            ]
            kind_changed = True

    if "description" in fields and fields["description"] is not None:
        node["description"] = clean_display_text(str(fields["description"]))

    if "aliases" in fields and fields["aliases"] is not None:
        node["aliases"] = clean_aliases(fields["aliases"], node["name"])
    else:
        node["aliases"] = clean_aliases(node.get("aliases", []), node["name"])

    affected_edge_ids: list[str] = []
    if kind_changed:
        for edge in project.get("edges", []):
            if edge.get("source") == node_id or edge.get("target") == node_id:
                affected_edge_ids.append(str(edge["id"]))
                if edge.get("status") != STATUS_REJECTED:
                    edge["status"] = STATUS_CHECK
                    edge["reviewed_at"] = ""
                    edge["override"] = False
                    edge["override_reason"] = ""

    note = str(fields.get("note") or "").strip()
    project.setdefault("curation_history", []).append(
        {
            "id": uid(),
            "request_id": str(fields.get("request_id") or ""),
            "at": now_iso(),
            "actor": str(fields.get("actor") or "human_reviewer"),
            "decision_origin": "human",
            "action": "edit_node",
            "target_id": node_id,
            "kind_changed": kind_changed,
            "affected_edge_ids": affected_edge_ids,
            "note": note,
            "before": before_node,
            "after": copy.deepcopy(node),
        }
    )
    return node


def _node_pair_fingerprint(node_a: dict, node_b: dict) -> str:
    payload = [
        {
            "id": node_a.get("id"),
            "name": normal(node_a.get("name", "")),
            "kind": normal(node_a.get("kind", "")),
            "aliases": sorted(normal(x) for x in node_a.get("aliases", [])),
        },
        {
            "id": node_b.get("id"),
            "name": normal(node_b.get("name", "")),
            "kind": normal(node_b.get("kind", "")),
            "aliases": sorted(normal(x) for x in node_b.get("aliases", [])),
        },
    ]
    payload.sort(key=lambda item: str(item["id"]))
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def mark_pair_not_duplicate(
    project: dict,
    node_a_id: str,
    node_b_id: str,
    note: str = "",
    *,
    actor: str = "human_reviewer",
) -> dict[str, Any]:
    """Đánh dấu một cặp gợi ý là 'Khác đối tượng' gắn với cặp ID và phiên bản thông tin hiện tại."""
    if node_a_id == node_b_id:
        raise ValueError("Hai thực thể phải khác nhau")
    node_a = find_node(project, node_a_id)
    node_b = find_node(project, node_b_id)
    if not node_a or not node_b:
        raise ValueError("Không tìm thấy thực thể trong cặp được chọn")

    pair_key = sorted([str(node_a_id), str(node_b_id)])
    fp = _node_pair_fingerprint(node_a, node_b)
    records = project.setdefault("not_duplicate_pairs", [])
    records = [r for r in records if sorted([str(r.get("node_a_id", "")), str(r.get("node_b_id", ""))]) != pair_key]
    entry = {
        "id": uid(),
        "node_a_id": pair_key[0],
        "node_b_id": pair_key[1],
        "pair_fingerprint": fp,
        "note": str(note or "").strip(),
        "actor": actor,
        "at": now_iso(),
    }
    records.append(entry)
    project["not_duplicate_pairs"] = records
    project.setdefault("curation_history", []).append(
        {
            "id": entry["id"],
            "at": entry["at"],
            "actor": actor,
            "decision_origin": "human",
            "action": "mark_not_duplicate",
            "target_id": f"{pair_key[0]}:{pair_key[1]}",
            "note": entry["note"],
            "before": None,
            "after": entry,
        }
    )
    return entry


def node_degrees(project: dict) -> dict[str, dict[str, int]]:
    """Tính bậc kết nối vào (in), ra (out) và tổng (total) cho từng thực thể trong dự án."""
    degrees: dict[str, dict[str, int]] = {
        str(n.get("id", "")): {"in": 0, "out": 0, "total": 0}
        for n in project.get("nodes", [])
        if n.get("id")
    }
    for edge in project.get("edges", []):
        if edge.get("status") == STATUS_REJECTED:
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src in degrees:
            degrees[src]["out"] += 1
            degrees[src]["total"] += 1
        if tgt in degrees:
            degrees[tgt]["in"] += 1
            degrees[tgt]["total"] += 1
    return degrees


def duplicate_suggestions(
    project: dict,
    fuzzy_threshold: float = 0.0,
    *,
    include_dismissed: bool = False,
) -> list[dict[str, Any]]:
    """Tìm các cặp thực thể nghi trùng (cache theo project_revision tránh O(n^2) mỗi lần rerun)."""
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    rev = compute_project_revision(project)
    cache_key = (proj_id, rev, float(fuzzy_threshold))

    if cache_key not in _DUPLICATE_SUGGESTIONS_CACHE:
        nodes = project.get("nodes", [])
        degs = node_degrees(project)
        pairs: list[dict[str, Any]] = []

        # 1. Tiền xử lý chuẩn hóa một lần cho toàn bộ node trong đồ thị
        norm_names = [normal(n.get("name", "")) for n in nodes]
        norm_aliases = [{normal(x) for x in n.get("aliases", []) if normal(x)} for n in nodes]

        # 2. Xây dựng Blocking Keys / Inverted Index để gom ứng viên nhanh
        name_to_indices: dict[str, list[int]] = {}
        alias_to_indices: dict[str, list[int]] = {}
        token_to_indices: dict[str, list[int]] = {}
        prefix_to_indices: dict[str, list[int]] = {}

        for idx, n_name in enumerate(norm_names):
            if n_name:
                name_to_indices.setdefault(n_name, []).append(idx)
                if len(n_name) >= 3:
                    prefix_to_indices.setdefault(n_name[:3], []).append(idx)
                for tok in set(n_name.split()):
                    if len(tok) >= 3:
                        token_to_indices.setdefault(tok, []).append(idx)
            for a_name in norm_aliases[idx]:
                alias_to_indices.setdefault(a_name, []).append(idx)

        # 3. Tập hợp các cặp ứng viên nghi ngờ (Candidate Blocking)
        candidate_pairs: set[tuple[int, int]] = set()

        def _add_pair(a_idx: int, b_idx: int) -> None:
            if a_idx != b_idx and nodes[a_idx].get("id") != nodes[b_idx].get("id"):
                candidate_pairs.add((min(a_idx, b_idx), max(a_idx, b_idx)))

        # Ứng viên trùng tên hoặc bí danh
        for idx_list in name_to_indices.values():
            if len(idx_list) > 1:
                for i_pos in range(len(idx_list)):
                    for j_pos in range(i_pos + 1, len(idx_list)):
                        _add_pair(idx_list[i_pos], idx_list[j_pos])

        for a_name, a_indices in alias_to_indices.items():
            if a_name in name_to_indices:
                for n_idx in name_to_indices[a_name]:
                    for a_idx in a_indices:
                        _add_pair(n_idx, a_idx)
            if len(a_indices) > 1:
                for i_pos in range(len(a_indices)):
                    for j_pos in range(i_pos + 1, len(a_indices)):
                        _add_pair(a_indices[i_pos], a_indices[j_pos])

        # Ứng viên qua token chung hoặc tiền tố (chỉ xét khi có fuzzy_threshold)
        if fuzzy_threshold:
            for tok, tok_indices in token_to_indices.items():
                if 1 < len(tok_indices) <= 60:
                    for i_pos in range(len(tok_indices)):
                        for j_pos in range(i_pos + 1, len(tok_indices)):
                            _add_pair(tok_indices[i_pos], tok_indices[j_pos])
            for pref, pref_indices in prefix_to_indices.items():
                if 1 < len(pref_indices) <= 60:
                    for i_pos in range(len(pref_indices)):
                        for j_pos in range(i_pos + 1, len(pref_indices)):
                            _add_pair(pref_indices[i_pos], pref_indices[j_pos])

        # Khi số node nhỏ (< 80), fallback kiểm tra toàn diện mọi cặp
        if len(nodes) < 80:
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    _add_pair(i, j)

        for (i, j) in candidate_pairs:
            if i == j:
                continue
            first = nodes[i]
            second = nodes[j]
            if first.get("id") == second.get("id"):
                continue
            name_a = norm_names[i]
            name_b = norm_names[j]
            aliases_a = norm_aliases[i]
            aliases_b = norm_aliases[j]

            reasons: list[str] = []
            if name_a and name_a == name_b:
                reasons.append("Trùng tên chuẩn hóa")
            if name_b in aliases_a or name_a in aliases_b:
                reasons.append("Tên này là bí danh của tên kia")
            if aliases_a & aliases_b:
                reasons.append("Có bí danh chung")

            len_a, len_b = len(name_a), len(name_b)
            max_len = max(len_a, len_b)
            score = 0.0
            if max_len > 0 and (abs(len_a - len_b) <= max_len * (1.0 - fuzzy_threshold + 0.05) or reasons):
                score = SequenceMatcher(None, name_a, name_b).ratio()
                if fuzzy_threshold and score >= fuzzy_threshold and not reasons:
                    reasons.append(f"Độ giống tên cao ({score:.2f})")

            if reasons:
                pair_fp = _node_pair_fingerprint(first, second)
                deg_a = degs.get(str(first["id"]), {"total": 0})["total"]
                deg_b = degs.get(str(second["id"]), {"total": 0})["total"]
                kind_conflict = normal(first.get("kind", "")) != normal(second.get("kind", ""))
                pairs.append(
                    {
                        "keep_id": first["id"],
                        "keep": first["name"],
                        "keep_kind": first.get("kind", ""),
                        "keep_docs": list(first.get("documents", [])),
                        "drop_id": second["id"],
                        "drop": second["name"],
                        "drop_kind": second.get("kind", ""),
                        "drop_docs": list(second.get("documents", [])),
                        "node_a": dict(first),
                        "node_b": dict(second),
                        "degree_a": deg_a,
                        "degree_b": deg_b,
                        "kind_conflict": kind_conflict,
                        "score": round(score, 2),
                        "name_similarity": round(score, 2),
                        "reason": "; ".join(reasons),
                        "pair_fingerprint": pair_fp,
                    }
                )

        pairs.sort(key=lambda x: -x["score"])
        if len(_DUPLICATE_SUGGESTIONS_CACHE) > 32:
            _DUPLICATE_SUGGESTIONS_CACHE.clear()
        _DUPLICATE_SUGGESTIONS_CACHE[cache_key] = pairs

    all_pairs = [dict(p) for p in _DUPLICATE_SUGGESTIONS_CACHE[cache_key]]
    dismissed_map: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in project.get("not_duplicate_pairs", []):
        k = tuple(sorted([str(rec.get("node_a_id", "")), str(rec.get("node_b_id", ""))]))
        dismissed_map[k] = rec  # type: ignore[index]

    filtered: list[dict[str, Any]] = []
    for p in all_pairs:
        kid = str(p.get("keep_id", "")).strip()
        did = str(p.get("drop_id", "")).strip()
        na_id = str((p.get("node_a") or {}).get("id", "")).strip()
        nb_id = str((p.get("node_b") or {}).get("id", "")).strip()
        if not kid or not did or kid == did or (na_id and nb_id and na_id == nb_id):
            continue
        k = tuple(sorted([kid, did]))
        dis = dismissed_map.get(k)  # type: ignore[arg-type]
        is_dismissed = bool(dis and dis.get("pair_fingerprint") == p["pair_fingerprint"])
        p["dismissed"] = is_dismissed
        p["dismissed_note"] = str(dis.get("note", "")) if is_dismissed and dis else ""
        if is_dismissed and not include_dismissed:
            continue
        filtered.append(p)
    return filtered


def clear_duplicate_suggestions_cache() -> None:
    """Xóa toàn bộ cache gợi ý thực thể nghi trùng trong bộ nhớ."""
    _DUPLICATE_SUGGESTIONS_CACHE.clear()


def compute_apparent_duplicate_edge_groups(edges: list[dict]) -> list[dict[str, Any]]:
    """Nhóm các cạnh có cùng (source, normal(relation), target) để hiển thị đối chiếu, KHÔNG tự xóa cạnh."""
    groups_map: dict[tuple[str, str, str], list[dict]] = {}
    for edge in edges:
        if edge.get("status") == STATUS_REJECTED:
            continue
        key = (
            str(edge.get("source", "")),
            normal(str(edge.get("relation", ""))),
            str(edge.get("target", "")),
        )
        groups_map.setdefault(key, []).append(edge)

    groups: list[dict[str, Any]] = []
    for (src, _, tgt), items in groups_map.items():
        if len(items) > 1:
            groups.append(
                {
                    "source": src,
                    "relation": items[0].get("relation", ""),
                    "target": tgt,
                    "edge_ids": [str(e["id"]) for e in items],
                    "count": len(items),
                    "evidences": [
                        {
                            "edge_id": str(e["id"]),
                            "doc_id": e.get("doc_id", ""),
                            "chunk_number": e.get("chunk_number", 0),
                            "start_char": e.get("start_char"),
                            "end_char": e.get("end_char"),
                            "evidence": e.get("evidence", ""),
                            "status": e.get("status", ""),
                        }
                        for e in items
                    ],
                }
            )
    return groups


def review_stats(project: dict, include_duplicates: bool = False) -> dict[str, int]:
    """Thống kê tổng quan cho dự án và Trang 4/5 với độ phức tạp tối ưu:
    - Precomputed catalog & nodes lookup cho schema_blocked (tránh N lần lặp O(K)).
    - Chunks được đếm bằng pointer arithmetic nhanh từ processor.
    - Cặp nghi trùng lặp chỉ chạy khi include_duplicates=True hoặc đã có trong cache."""
    edges = project.get("edges", [])

    precomputed = {
        "proposals": {str(p.get("id", "")): p for p in project.get("schema_proposals", [])},
        "nodes": {str(n.get("id", "")): n for n in project.get("nodes", [])},
        "rel_norms": {normal(r["name"]) for r in catalog_rows(project, "relations")},
        "type_norms": {normal(t["name"]) for t in catalog_rows(project, "entity_types")},
    }

    schema_blocked = sum(
        1
        for e in edges
        if e.get("status") != STATUS_REJECTED
        and inspect_edge_schema_status(project, e, precomputed=precomputed)["status_code"] != "valid"
    )

    if include_duplicates:
        dup_pairs = len(duplicate_suggestions(project, fuzzy_threshold=0.82))
    else:
        cache_key = (
            str(project.get("project_id") or project.get("name") or "default"),
            compute_project_revision(project),
            0.82,
        )
        if cache_key in _DUPLICATE_SUGGESTIONS_CACHE:
            dup_pairs = len(_DUPLICATE_SUGGESTIONS_CACHE[cache_key])
        else:
            dup_pairs = -1

    return {
        "documents": len(project.get("documents", [])),
        "chunks": sum(count_chunks(d.get("text", "")) for d in project.get("documents", [])),
        "nodes": len(project.get("nodes", [])),
        "edges": len(edges),
        "approved": sum(1 for e in edges if e.get("status") == STATUS_APPROVED),
        "pending": sum(1 for e in edges if e.get("status") == STATUS_PENDING),
        "check": sum(1 for e in edges if e.get("status") == STATUS_CHECK),
        "rejected": sum(1 for e in edges if e.get("status") == STATUS_REJECTED),
        "schema_blocked": schema_blocked,
        "duplicate_pairs": dup_pairs,
    }


def token_totals(project: dict) -> dict[str, int]:
    runs = project.get("runs", [])
    return {
        "runs": len(runs),
        "input_tokens": sum(int(r.get("input_tokens", 0) or 0) for r in runs),
        "output_tokens": sum(int(r.get("output_tokens", 0) or 0) for r in runs),
        "errors": len(project.get("chunk_errors", {})),
    }

