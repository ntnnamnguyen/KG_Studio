"""Các hàm tiện ích và cấu trúc thuật toán dùng chung cho Gộp Thực thể, Quan hệ và Thu gọn Bộ ba."""
from __future__ import annotations

import copy
from typing import Any

from shared.constants import (
    STATUS_APPROVED,
    STATUS_CHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from shared.text_utils import normal


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


def normalize_pair_key(a: str, b: str, use_normal: bool = True) -> tuple[str, str]:
    """Chuẩn hóa khóa của một cặp đối xứng (A, B) == (B, A)."""
    val_a = normal(str(a or "")) if use_normal else str(a or "").strip()
    val_b = normal(str(b or "")) if use_normal else str(b or "").strip()
    return (val_a, val_b) if val_a <= val_b else (val_b, val_a)


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
