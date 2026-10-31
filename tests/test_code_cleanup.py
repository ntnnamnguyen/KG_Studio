"""Kiểm thử tính tương đương và ổn định sau đợt dọn dẹp, tái cấu trúc mã nguồn (Code Cleanup Tests)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from backend.domain.curation import (
    _DUPLICATE_SUGGESTIONS_CACHE,
    apply_curation_decisions,
    apply_entity_merge,
    approvable_edges,
    clean_aliases,
    clean_display_text,
    compute_apparent_duplicate_edge_groups,
    compute_curation_decisions_hash,
    compute_curation_request_hash,
    compute_entity_merge_hash,
    doc_fingerprint,
    duplicate_suggestions,
    evidence_context,
    evidence_in_chunk,
    find_all_quote_spans,
    find_document,
    find_edge,
    find_node,
    find_quote_span,
    is_edge_exportable,
    mark_pair_not_duplicate,
    merge_nodes,
    node_degrees,
    preview_curation_decisions,
    preview_entity_merge,
    recheck_edge_evidence,
    resolve_active_node_id,
    review_stats,
    select_edge_evidence_span,
    set_edge_status,
    set_edges_status,
    token_totals,
    update_edge,
    update_node,
    validate_edge_for_approval,
)
import backend.domain.curation.common as curation_common
import backend.domain.curation.entities as curation_entities
import backend.domain.curation.evidence as curation_evidence
import backend.domain.curation.merge as curation_merge
import backend.domain.curation.review as curation_review
import backend.domain.curation.service as curation_service
import backend.domain.curation.validation as curation_validation
from backend.facade import KGStudioFacade
from frontend.state.selection_core import (
    append_unique_ids,
    reconcile_id_selection,
    toggle_id_in_list,
)
from ml_lab.trainers.dataset_io import load_jsonl
from shared.config_loader import default_catalogs


class CodeCleanupParityTests(unittest.TestCase):
    """Kiểm chứng tính toàn vẹn và tương thích 100% sau khi phân rã module và gom helper."""

    def test_default_catalogs_returns_empty_contract(self):
        cats = default_catalogs()
        self.assertEqual(cats, {"relations": [], "entity_types": []})

    def test_ml_lab_load_jsonl_semantics(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "test.jsonl"
            # Tệp chưa tồn tại -> trả rỗng
            self.assertEqual(load_jsonl(tmp_path), [])

            # Ghi dòng trắng, dòng hợp lệ, unicode tiếng Việt
            tmp_path.write_text(
                '{"id": 1, "text": "Hà Nội"}\n\n   \n{"id": 2, "text": "Đà Nẵng"}\n',
                encoding="utf-8",
            )
            rows = load_jsonl(tmp_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["text"], "Hà Nội")
            self.assertEqual(rows[1]["id"], 2)

    def test_selection_core_helpers_order_and_types(self):
        # 1. Toggle ID in list
        lst: list[str] = ["a", "b"]
        # Add duplicate
        self.assertEqual(toggle_id_in_list(lst, "a", True, True), ["a", "b"])
        # Add new eligible
        self.assertEqual(toggle_id_in_list(lst, "c", True, True), ["a", "b", "c"])
        # Add new ineligible
        self.assertEqual(toggle_id_in_list(lst, "d", True, False), ["a", "b", "c"])
        # Remove
        self.assertEqual(toggle_id_in_list(lst, "b", False, True), ["a", "c"])

        # 2. Append unique IDs
        base: list[str] = ["x", "y"]
        res = append_unique_ids(base, ["y", "z", "w", "x"])
        self.assertEqual(res, ["x", "y", "z", "w"])

        # 3. Reconcile ID selection
        curr = ["1", "2", "3", "4"]
        eligible_set = {"2", "4", "5"}
        # Same signature
        kept, pruned, notice = reconcile_id_selection(curr, eligible_set, "sig1", "sig1")
        self.assertEqual(kept, ["2", "4"])
        self.assertEqual(pruned, 0)
        self.assertEqual(notice, "")

        # Changed signature
        kept2, pruned2, notice2 = reconcile_id_selection(curr, eligible_set, "sig1", "sig2", item_noun="cạnh")
        self.assertEqual(kept2, ["2", "4"])
        self.assertEqual(pruned2, 2)
        self.assertIn("Đã bỏ chọn 2 cạnh", notice2)

    def test_curation_service_and_submodules_identity(self):
        # Kiểm tra tính tương đồng tham chiếu của các module con với facade service.py
        self.assertIs(curation_service.clean_display_text, curation_common.clean_display_text)
        self.assertIs(curation_service.doc_fingerprint, curation_common.doc_fingerprint)
        self.assertIs(curation_service.evidence_context, curation_evidence.evidence_context)
        self.assertIs(curation_service.validate_edge_for_approval, curation_validation.validate_edge_for_approval)
        self.assertIs(curation_service.set_edge_status, curation_review.set_edge_status)
        self.assertIs(curation_service.apply_entity_merge, curation_merge.apply_entity_merge)

        # Kiểm tra bộ nhớ đệm dùng chung 1 đối tượng duy nhất
        self.assertIs(curation_service._DUPLICATE_SUGGESTIONS_CACHE, curation_entities._DUPLICATE_SUGGESTIONS_CACHE)

    def test_facade_sqlite_sync_safe_and_revision_protection(self):
        fake_json_repo = MagicMock()
        fake_sqlite_repo = MagicMock()
        facade = KGStudioFacade(json_repo=fake_json_repo, sqlite_repo=fake_sqlite_repo)

        # 1. Sync thành công
        proj = {"name": "test_proj", "project_id": "p1"}
        status, err = facade._sync_sqlite_safe(proj)
        self.assertEqual(status, "synced")
        self.assertFalse(proj["sync_pending"])
        self.assertEqual(proj["sync_error"], "")

        # 2. Sync lỗi SQLite -> không raise, đánh dấu pending
        fake_sqlite_repo.sync_from_project_dict.side_effect = RuntimeError("DB locked")
        status, err = facade._sync_sqlite_safe(proj)
        self.assertEqual(status, "sync_pending")
        self.assertTrue(proj["sync_pending"])
        self.assertIn("DB locked", err)

        # 3. Revision conflict check
        facade._last_committed_revision["p1"] = "rev_999"
        proj["name"] = "p1"
        fake_json_repo.project_exists.return_value = False
        with self.assertRaises(ValueError) as ctx:
            facade._check_revision_conflict("p1", "p1", proj, "rev_100")
        self.assertIn("revision mismatch", str(ctx.exception))

    def test_facade_has_no_write_only_previews_leak(self):
        facade = KGStudioFacade()
        self.assertFalse(hasattr(facade, "_previews"))


if __name__ == "__main__":
    unittest.main()

