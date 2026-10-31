"""Tầng dùng chung (Shared Layer) của KG Studio — không phụ thuộc Backend, Frontend hay ML Lab."""
from __future__ import annotations

from .constants import (
    DEFAULT_EDC_PLUS_R_SETTINGS,
    EXTRACTION_MODES,
    MODE_EDC,
    MODE_EDC_PLUS_R,
    MODE_FIXED,
    SCHEMA_VERSION,
    SECRET_KEYS,
    STATUS_APPROVED,
    STATUS_CHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUSES,
)
from .secrets_manager import (
    delete_api_key,
    get_api_key,
    has_persisted_key,
    list_saved_providers,
    mask_api_key,
    save_api_key,
)
from .text_utils import normal, now_iso, safe_filename, scrubbed, sha, slug, tokenize_vn, uid

__all__ = [
    "DEFAULT_EDC_PLUS_R_SETTINGS",
    "EXTRACTION_MODES",
    "MODE_EDC",
    "MODE_EDC_PLUS_R",
    "MODE_FIXED",
    "SCHEMA_VERSION",
    "SECRET_KEYS",
    "STATUS_APPROVED",
    "STATUS_CHECK",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "STATUSES",
    "delete_api_key",
    "get_api_key",
    "has_persisted_key",
    "list_saved_providers",
    "mask_api_key",
    "save_api_key",
    "normal",
    "now_iso",
    "safe_filename",
    "scrubbed",
    "sha",
    "slug",
    "tokenize_vn",
    "uid",
]

