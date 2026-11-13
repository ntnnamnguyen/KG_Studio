"""Logic lọc, sắp xếp và tạo dữ liệu bảng cho danh sách thực thể (Trang 4)."""
from __future__ import annotations

from typing import Any

from backend.domain.curation.service import duplicate_suggestions, node_degrees
from shared.text_utils import normal


def filter_and_sort_entities(
    project: dict,
    filters: dict[str, Any],
    *,
    dup_node_ids: set[str] | None = None,
) -> list[dict]:
    """Lọc và sắp xếp danh sách thực thể cho Khu vực B (mục 6.1)."""
    degrees = node_degrees(project)
    proposals = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    type_norms = {normal(t["name"]) for t in project.get("entity_types", []) if t.get("name")}
    f_kind = str(filters.get("kind") or "all")
    f_doc = str(filters.get("doc_id") or "all")
    f_schema = str(filters.get("schema_state") or "all")
    f_deg = str(filters.get("degree_filter") or "all")
    f_dup = bool(filters.get("dup_candidate_only", False))
    f_search = normal(str(filters.get("search") or ""))

    if dup_node_ids is None:
        if f_dup:
            sugs = duplicate_suggestions(project, fuzzy_threshold=0.82)
            dup_node_ids = {
                str(x)
                for s in sugs
                for x in (
                    s.get("keep_id", s.get("node_a", {}).get("id")),
                    s.get("drop_id", s.get("node_b", {}).get("id")),
                )
            }
        else:
            dup_node_ids = set()

    matched: list[dict] = []
    for node in project.get("nodes", []):
        nid = str(node.get("id", ""))
        if f_kind != "all" and normal(node.get("kind", "")) != normal(f_kind):
            continue
        if f_doc != "all" and f_doc not in node.get("documents", []):
            continue
        if f_dup and nid not in dup_node_ids:
            continue

        deg_total = degrees.get(nid, {"total": 0})["total"]
        if f_deg == "isolated" and deg_total != 0:
            continue
        if f_deg == "gte_1" and deg_total < 1:
            continue
        if f_deg == "gte_3" and deg_total < 3:
            continue

        has_pending_prop = any(
            proposals.get(str(pid), {}).get("status") == "pending"
            for pid in node.get("schema_proposal_ids", [])
        )
        in_catalog = normal(node.get("kind", "")) in type_norms
        if f_schema == "valid" and (has_pending_prop or not in_catalog):
            continue
        if f_schema == "blocked" and not has_pending_prop and in_catalog:
            continue

        if f_search:
            hay = " ".join(
                [
                    str(node.get("name", "")),
                    str(node.get("kind", "")),
                    str(node.get("description", "")),
                    " ".join(str(a) for a in node.get("aliases", [])),
                ]
            )
            if f_search not in normal(hay):
                continue

        matched.append(node)

    sort_by = str(filters.get("sort_by") or "degree_desc")
    if sort_by == "name":
        matched.sort(key=lambda n: (normal(n.get("name", "")), str(n.get("id", ""))))
    elif sort_by == "kind":
        matched.sort(key=lambda n: (normal(n.get("kind", "")), normal(n.get("name", ""))))
    else:
        matched.sort(
            key=lambda n: (-degrees.get(str(n.get("id", "")), {"total": 0})["total"], normal(n.get("name", "")))
        )
    return matched


def build_entity_table_rows(project: dict, nodes: list[dict]) -> list[dict[str, Any]]:
    """Tạo dữ liệu hiển thị cho bảng thực thể."""
    degrees = node_degrees(project)
    proposals = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
    type_norms = {normal(t["name"]) for t in project.get("entity_types", []) if t.get("name")}
    rows: list[dict[str, Any]] = []
    for node in nodes:
        nid = str(node.get("id", ""))
        deg = degrees.get(nid, {"in": 0, "out": 0, "total": 0})
        pending_pids = [
            str(pid)
            for pid in node.get("schema_proposal_ids", [])
            if proposals.get(str(pid), {}).get("status") == "pending"
        ]
        if pending_pids:
            schema_label = "Còn đề xuất chờ"
        elif normal(node.get("kind", "")) in type_norms:
            schema_label = "Đã chuẩn hóa"
        else:
            schema_label = "Ngoài danh mục"
        desc = str(node.get("description") or "").strip()
        rows.append(
            {
                "node_id": nid,
                "name": str(node.get("name", "")),
                "kind": str(node.get("kind", "")),
                "aliases_display": "; ".join(node.get("aliases", [])),
                "description_snippet": desc if len(desc) <= 80 else f"{desc[:77]}...",
                "doc_count": len(node.get("documents", [])),
                "degree_display": f"{deg['total']} (Vào: {deg['in']} · Ra: {deg['out']})",
                "degree_total": deg["total"],
                "schema_label": schema_label,
                "pending_proposal_ids": pending_pids,
            }
        )
    return rows
