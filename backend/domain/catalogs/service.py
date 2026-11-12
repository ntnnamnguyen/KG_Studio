"""Service Quản lý Danh mục, Prompt và Đề xuất EDC (Phân rã theo trách nhiệm - Gate P5).
Tái xuất toàn bộ API từ các submodules chuyên biệt:
- core.py: Catalog CRUD/hash, prompt settings, project revision, request hashes.
- proposals.py: Tiếp nhận đề xuất, phát hiện stale candidates, tính phạm vi ảnh hưởng.
- review.py: Xem trước (preview) và áp dụng (apply) các quyết định duyệt hàng loạt.
"""
from __future__ import annotations

from backend.domain.catalogs.core import (
    catalog_rows,
    compute_catalog_hash,
    compute_decisions_hash,
    compute_full_request_hash,
    compute_project_revision,
    extraction_prompt,
    prompt_signature,
    save_prompt_settings,
)
from backend.domain.catalogs.proposals import (
    batch_proposal_impacts,
    is_proposal_candidates_stale,
    prepare_edc,
    proposal_impact,
    propose_term,
    schema_review_issue,
)
from backend.domain.catalogs.review import (
    _clone_project_for_edc_mutation,
    _default_description_for_approval,
    apply_proposal_decisions,
    decide_proposal,
    preview_proposal_decisions,
)
from shared.catalog_utils import apply_relations, catalog_bytes, parse_catalog, relation_catalog

__all__ = [
    "prompt_signature",
    "extraction_prompt",
    "save_prompt_settings",
    "catalog_rows",
    "compute_catalog_hash",
    "compute_project_revision",
    "compute_decisions_hash",
    "compute_full_request_hash",
    "is_proposal_candidates_stale",
    "propose_term",
    "prepare_edc",
    "schema_review_issue",
    "batch_proposal_impacts",
    "proposal_impact",
    "_default_description_for_approval",
    "_clone_project_for_edc_mutation",
    "decide_proposal",
    "preview_proposal_decisions",
    "apply_proposal_decisions",
]
