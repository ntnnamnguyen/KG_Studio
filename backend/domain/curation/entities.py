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

from .merge_core import (
    filter_dismissed_pairs,
    generate_candidate_index_pairs,
    group_edges_by_triplet,
    normalize_pair_key,
    score_text_pair_similarity,
)
from .common import clean_aliases, clean_display_text, find_node
from .validation import build_schema_precomputed, inspect_edge_schema_status

# Bộ nhớ đệm gợi ý trùng lặp theo (project_id, revision, fuzzy_threshold) tránh tính lại O(n^2) mỗi lần rerun
_DUPLICATE_SUGGESTIONS_CACHE: dict[tuple[str, str, float], list[dict[str, Any]]] = {}


def update_node(project: dict, node_id: str, req: Any = None, **fields) -> dict:
    """Cập nhật hồ sơ thực thể theo đúng Ma trận ảnh hưởng mục 8.2:
    - Sửa tên hiển thị, bí danh hoặc mô tả (không đổi loại) -> giữ ID, lưu audit, KHÔNG tự thay đổi trạng thái cạnh.
    - Đổi loại node (chỉ cho phép chọn từ catalog đã duyệt) -> các cạnh nối node chuyển về Cần kiểm tra (trừ cạnh Loại bỏ).
    Hỗ trợ nhận trực tiếp EntityEditRequestDTO (Pydantic v2) hoặc các tham số kwargs.
    """
    if req is not None:
        req_data = req.to_dict() if hasattr(req, "to_dict") else dict(req)
        for k, v in req_data.items():
            if v is not None and k not in fields and k not in ("node_id", "project_id", "expected_revision"):
                fields[k] = v
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

    pk = normalize_pair_key(node_a_id, node_b_id, use_normal=False)
    fp = _node_pair_fingerprint(node_a, node_b)
    records = project.setdefault("not_duplicate_pairs", [])
    records = [r for r in records if normalize_pair_key(r.get("node_a_id", ""), r.get("node_b_id", ""), use_normal=False) != pk]
    entry = {
        "id": uid(),
        "node_a_id": pk[0],
        "node_b_id": pk[1],
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
            "target_id": f"{pk[0]}:{pk[1]}",
            "note": entry["note"],
            "before": None,
            "after": entry,
        }
    )
    return entry


def mark_pairs_not_duplicate_bulk(
    project: dict,
    pairs: list[tuple[str, str] | list[str] | dict[str, Any]],
    note: str = "",
    *,
    actor: str = "human_reviewer",
) -> list[dict[str, Any]]:
    """Đánh dấu hàng loạt cặp thực thể là 'Khác đối tượng' trong một lần quét O(V + K)."""
    if not pairs:
        return []
    nodes_by_id = {str(n.get("id", "")): n for n in project.get("nodes", []) if n.get("id")}
    existing_records = project.get("not_duplicate_pairs", [])
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    ordered_keys: list[tuple[str, str]] = []
    for r in existing_records:
        rk = normalize_pair_key(str(r.get("node_a_id", "")), str(r.get("node_b_id", "")), use_normal=False)
        if rk not in by_key:
            ordered_keys.append(rk)  # type: ignore[arg-type]
        by_key[rk] = r  # type: ignore[index]

    clean_note = str(note or "").strip()
    ts = now_iso()
    history = project.setdefault("curation_history", [])
    created: list[dict[str, Any]] = []

    for item in pairs:
        if isinstance(item, dict):
            a_id = str(item.get("keep_id") or item.get("node_a_id") or "").strip()
            b_id = str(item.get("drop_id") or item.get("node_b_id") or "").strip()
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            a_id, b_id = str(item[0]).strip(), str(item[1]).strip()
        else:
            continue
        if not a_id or not b_id or a_id == b_id:
            continue
        node_a = nodes_by_id.get(a_id)
        node_b = nodes_by_id.get(b_id)
        if not node_a or not node_b:
            continue

        pk = normalize_pair_key(a_id, b_id, use_normal=False)
        fp = _node_pair_fingerprint(node_a, node_b)
        entry = {
            "id": uid(),
            "node_a_id": pk[0],
            "node_b_id": pk[1],
            "pair_fingerprint": fp,
            "note": clean_note,
            "actor": actor,
            "at": ts,
        }
        if pk not in by_key:
            ordered_keys.append(pk)  # type: ignore[arg-type]
        by_key[pk] = entry  # type: ignore[index]
        created.append(entry)
        history.append(
            {
                "id": entry["id"],
                "at": ts,
                "actor": actor,
                "decision_origin": "human",
                "action": "mark_not_duplicate",
                "target_id": f"{pk[0]}:{pk[1]}",
                "note": clean_note,
                "before": None,
                "after": entry,
            }
        )

    project["not_duplicate_pairs"] = [by_key[k] for k in ordered_keys]
    return created


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

        # 2. Gom ứng viên nhanh bằng Inverted Index & Token Blocking dùng chung
        candidate_pairs = generate_candidate_index_pairs(
            norm_names,
            norm_aliases,
            fuzzy_threshold=fuzzy_threshold,
            force_all_threshold=80,
            max_bucket_size=60,
        )

        for (i, j) in candidate_pairs:
            first = nodes[i]
            second = nodes[j]
            if first.get("id") == second.get("id"):
                continue

            score, reasons = score_text_pair_similarity(
                norm_names[i],
                norm_names[j],
                norm_aliases[i],
                norm_aliases[j],
                fuzzy_threshold=fuzzy_threshold,
            )

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
                        "score": score,
                        "name_similarity": score,
                        "reason": "; ".join(reasons),
                        "pair_fingerprint": pair_fp,
                    }
                )

        pairs.sort(key=lambda x: -x["score"])
        if len(_DUPLICATE_SUGGESTIONS_CACHE) > 32:
            _DUPLICATE_SUGGESTIONS_CACHE.clear()
        _DUPLICATE_SUGGESTIONS_CACHE[cache_key] = pairs

    all_pairs = [dict(p) for p in _DUPLICATE_SUGGESTIONS_CACHE[cache_key]]
    return filter_dismissed_pairs(
        all_pairs,
        project.get("not_duplicate_pairs", []),
        id_a_key="keep_id",
        id_b_key="drop_id",
        fp_key="pair_fingerprint",
        include_dismissed=include_dismissed,
    )


def clear_duplicate_suggestions_cache() -> None:
    """Xóa toàn bộ cache gợi ý thực thể nghi trùng trong bộ nhớ."""
    _DUPLICATE_SUGGESTIONS_CACHE.clear()


def compute_apparent_duplicate_edge_groups(edges: list[dict]) -> list[dict[str, Any]]:
    """Nhóm các cạnh có cùng bộ ba (source, normal(relation), target) sử dụng group_edges_by_triplet."""
    groups_map = group_edges_by_triplet(edges, exclude_rejected=True)
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
    return groups


def review_stats(project: dict, include_duplicates: bool = False) -> dict[str, int]:
    """Thống kê tổng quan cho dự án và Trang 4/5 với độ phức tạp tối ưu:
    - Precomputed catalog & nodes lookup cho schema_blocked (tránh N lần lặp O(K)).
    - Chunks được đếm bằng pointer arithmetic nhanh từ processor.
    - Cặp nghi trùng lặp chỉ chạy khi include_duplicates=True hoặc đã có trong cache."""
    edges = project.get("edges", [])
    precomputed = build_schema_precomputed(project)

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
            raw_cached = [dict(p) for p in _DUPLICATE_SUGGESTIONS_CACHE[cache_key]]
            dup_pairs = len(
                filter_dismissed_pairs(
                    raw_cached,
                    project.get("not_duplicate_pairs", []),
                    id_a_key="keep_id",
                    id_b_key="drop_id",
                    fp_key="pair_fingerprint",
                    include_dismissed=False,
                )
            )
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

