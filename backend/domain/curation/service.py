"""Kiểm duyệt dữ kiện, đối chiếu bằng chứng, quản lý hồ sơ thực thể và gộp thực thể an toàn (Độc lập 100%).

Module này đóng vai trò Facade và điểm kết nối tương thích ngược 100% cho toàn bộ phân khu Curation.
Các trách nhiệm chi tiết được phân rã theo miền:
- common.py: Tra cứu thực thể, quan hệ, tài liệu và chuẩn hóa chuỗi cơ sở.
- evidence.py: Đối chiếu trích dẫn bằng chứng, tính fingerprint và định vị span ký tự.
- validation.py: Kiểm tra ràng buộc schema, điều kiện duyệt và tính xuất đồ thị.
- review.py: Duyệt đơn, duyệt lô và chỉnh sửa quan hệ với revision protection.
- entities.py: Quản lý hồ sơ thực thể, bậc đồ thị, phát hiện trùng lặp và thống kê.
- merge.py: Xem trước và thực thi gộp N thực thể an toàn, bảo toàn cạnh và ánh xạ node_redirects.
"""
from __future__ import annotations

from .common import (
    clean_aliases,
    clean_display_text,
    doc_fingerprint,
    find_document,
    find_edge,
    find_node,
    resolve_active_node_id,
)
from .entities import (
    _DUPLICATE_SUGGESTIONS_CACHE,
    compute_apparent_duplicate_edge_groups,
    duplicate_suggestions,
    mark_pair_not_duplicate,
    mark_pairs_not_duplicate_bulk,
    node_degrees,
    review_stats,
    token_totals,
    update_node,
)
from .evidence import (
    evidence_context,
    evidence_in_chunk,
    find_all_quote_spans,
    find_quote_span,
    recheck_edge_evidence,
    select_edge_evidence_span,
)
from .merge import (
    apply_bulk_entity_merges,
    apply_entity_merge,
    apply_relation_merge,
    bulk_apply_relation_merges,
    collapse_duplicate_edges,
    compute_entity_merge_hash,
    mark_relation_pair_not_duplicate,
    mark_relation_pairs_not_duplicate_bulk,
    merge_nodes,
    preview_entity_merge,
    relation_duplicate_suggestions,
)
from .semantic_clustering import (
    apply_semantic_clusters,
    bulk_apply_entity_type_merges,
    canonical_key,
    preview_clustering_prompt,
    scan_semantic_clusters,
)
from .review import (
    _normalize_review_action,
    apply_curation_decisions,
    compute_curation_decisions_hash,
    compute_curation_request_hash,
    preview_curation_decisions,
    set_edge_status,
    set_edges_status,
    update_edge,
)
from .validation import (
    approvable_edges,
    build_curation_validation_context,
    build_schema_precomputed,
    inspect_edge_schema_status,
    is_edge_exportable,
    validate_edge_for_approval,
)

__all__ = [
    # Common
    "clean_display_text",
    "clean_aliases",
    "doc_fingerprint",
    "find_document",
    "resolve_active_node_id",
    "find_node",
    "find_edge",
    # Evidence
    "evidence_in_chunk",
    "find_all_quote_spans",
    "find_quote_span",
    "evidence_context",
    "select_edge_evidence_span",
    "recheck_edge_evidence",
    # Validation
    "build_schema_precomputed",
    "build_curation_validation_context",
    "inspect_edge_schema_status",
    "validate_edge_for_approval",
    "is_edge_exportable",
    "approvable_edges",
    # Review
    "_normalize_review_action",
    "set_edge_status",
    "set_edges_status",
    "compute_curation_decisions_hash",
    "compute_curation_request_hash",
    "preview_curation_decisions",
    "apply_curation_decisions",
    "update_edge",
    # Entities
    "_DUPLICATE_SUGGESTIONS_CACHE",
    "update_node",
    "mark_pair_not_duplicate",
    "node_degrees",
    "duplicate_suggestions",
    "compute_apparent_duplicate_edge_groups",
    "review_stats",
    "token_totals",
    # Merge
    "compute_entity_merge_hash",
    "preview_entity_merge",
    "apply_entity_merge",
    "apply_bulk_entity_merges",
    "relation_duplicate_suggestions",
    "apply_relation_merge",
    "bulk_apply_relation_merges",
    "collapse_duplicate_edges",
    "mark_relation_pair_not_duplicate",
    "merge_nodes",
    # Semantic Clustering
    "preview_clustering_prompt",
    "scan_semantic_clusters",
    "apply_semantic_clusters",
    "bulk_apply_entity_type_merges",
]
