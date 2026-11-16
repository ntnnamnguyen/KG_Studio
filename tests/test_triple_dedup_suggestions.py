"""Kiểm thử hệ thống Gợi ý & Khử trùng Cạnh Lặp theo Bộ ba (Triple Deduplication Suggestions & Selective Collapse)."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from backend.facade import KGStudioFacade
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from frontend.state.session import bump_sync_nonce, sync_keyed_value
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING


class TripleDedupSuggestionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.facade = KGStudioFacade(json_repo=JsonProjectRepository(Path(self.tmp_dir.name)))

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _create_sample_project(self) -> dict:
        proj = empty_project("TripleDedupProj")
        proj["nodes"] = [
            {"id": "n_chua", "name": "Chùa Một Cột", "kind": "Di tích"},
            {"id": "n_vua", "name": "Lý Thái Tông", "kind": "Nhân vật"},
            {"id": "n_nam", "name": "1049", "kind": "Thời gian"},
            {"id": "n_van_mieu", "name": "Văn Miếu", "kind": "Di tích"},
        ]
        proj["edges"] = [
            # Nhóm 1: Trùng bộ ba tuyệt đối (Exact Triplet = 1.00)
            {
                "id": "e_exact_1",
                "source": "n_chua",
                "relation": "tọa lạc tại",
                "target": "n_van_mieu",
                "evidence": "Chùa Một Cột nằm gần quần thể Ba Đình.",
                "doc_id": "doc_1",
                "chunk_number": 1,
                "status": STATUS_PENDING,
            },
            {
                "id": "e_exact_2",
                "source": "n_chua",
                "relation": "Tọa lạc tại",
                "target": "n_van_mieu",
                "evidence": "Di tích Chùa Một Cột tọa lạc tại khu vực trung tâm lịch sử.",
                "doc_id": "doc_2",
                "chunk_number": 2,
                "status": STATUS_APPROVED,
            },
            # Nhóm 2: Cùng cặp nút (n_chua -> n_nam) nhưng vị từ tương đồng (Fuzzy Relation)
            {
                "id": "e_fuzzy_1",
                "source": "n_chua",
                "relation": "được xây dựng vào năm",
                "target": "n_nam",
                "evidence": "Chùa Một Cột được xây dựng vào năm 1049.",
                "doc_id": "doc_1",
                "chunk_number": 1,
                "status": STATUS_APPROVED,
            },
            {
                "id": "e_fuzzy_2",
                "source": "n_chua",
                "relation": "xây dựng năm",
                "target": "n_nam",
                "evidence": "Chùa xây dựng năm 1049 đời Lý.",
                "doc_id": "doc_2",
                "chunk_number": 3,
                "status": STATUS_CHECK,
            },
            # Nhóm 3: Ngược chiều Chủ động - Bị động giữa (n_vua <-> n_chua)
            {
                "id": "e_inv_active",
                "source": "n_vua",
                "relation": "cho xây dựng",
                "target": "n_chua",
                "evidence": "Vua Lý Thái Tông cho xây dựng Chùa Một Cột.",
                "doc_id": "doc_1",
                "chunk_number": 1,
                "status": STATUS_APPROVED,
            },
            {
                "id": "e_inv_passive",
                "source": "n_chua",
                "relation": "được xây dựng bởi",
                "target": "n_vua",
                "evidence": "Chùa Một Cột được xây dựng bởi vua Lý Thái Tông.",
                "doc_id": "doc_2",
                "chunk_number": 4,
                "status": STATUS_PENDING,
            },
        ]
        self.facade.save_project(proj)
        return proj

    def test_three_tier_triple_duplicate_suggestions(self) -> None:
        """Kiểm chứng phát hiện đầy đủ 3 tầng gợi ý: exact_triplet, fuzzy_relation và inverse_pair."""
        proj = self._create_sample_project()
        suggestions = self.facade.triple_duplicate_suggestions(proj, fuzzy_threshold=0.65)
        by_type = {s["match_type"]: s for s in suggestions}

        self.assertIn("exact_triplet", by_type)
        self.assertIn("fuzzy_relation", by_type)
        self.assertIn("inverse_pair", by_type)

        # Kiểm tra nhóm trùng 100%: cạnh Đã duyệt (e_exact_2) phải được chọn làm representative_id
        exact_grp = by_type["exact_triplet"]
        self.assertEqual(exact_grp["score"], 1.0)
        self.assertEqual(exact_grp["representative_id"], "e_exact_2")
        self.assertEqual(set(exact_grp["edge_ids"]), {"e_exact_1", "e_exact_2"})

        # Kiểm tra nhóm vị từ tương đồng cùng cặp nút
        fuzzy_grp = by_type["fuzzy_relation"]
        self.assertGreaterEqual(fuzzy_grp["score"], 0.65)
        self.assertEqual(fuzzy_grp["representative_id"], "e_fuzzy_1")
        self.assertEqual(set(fuzzy_grp["edge_ids"]), {"e_fuzzy_1", "e_fuzzy_2"})

        # Kiểm tra nhóm đảo chiều Chủ động - Bị động: ưu tiên cạnh chủ động (e_inv_active) làm cạnh đại diện
        inv_grp = by_type["inverse_pair"]
        self.assertEqual(inv_grp["representative_id"], "e_inv_active")
        self.assertEqual(inv_grp["relation"], "cho xây dựng")

    def test_selective_collapse_preserves_unselected_and_consolidates_evidence(self) -> None:
        """Kiểm chứng hợp nhất có chọn lọc (Selective Collapse) chỉ gộp nhóm được chọn và bảo toàn 100% bằng chứng."""
        proj = self._create_sample_project()
        suggestions = self.facade.triple_duplicate_suggestions(proj, fuzzy_threshold=0.65)
        fuzzy_grp = next(s for s in suggestions if s["match_type"] == "fuzzy_relation")
        fuzzy_grp["canonical_relation"] = "được xây dựng năm"

        res = self.facade.collapse_duplicate_edges(
            proj,
            selected_groups=[fuzzy_grp],
            note="Gộp chọn lọc nhóm vị từ tương đồng",
        )
        self.assertEqual(res.merged_duplicate_edges, 1)

        remaining_ids = {e["id"] for e in proj["edges"]}
        # Cạnh e_fuzzy_2 đã được gộp vào e_fuzzy_1
        self.assertIn("e_fuzzy_1", remaining_ids)
        self.assertNotIn("e_fuzzy_2", remaining_ids)
        # Các nhóm không chọn (e_exact_1, e_exact_2, e_inv_active, e_inv_passive) vẫn được giữ nguyên
        self.assertIn("e_exact_1", remaining_ids)
        self.assertIn("e_exact_2", remaining_ids)
        self.assertIn("e_inv_active", remaining_ids)
        self.assertIn("e_inv_passive", remaining_ids)

        kept_edge = next(e for e in proj["edges"] if e["id"] == "e_fuzzy_1")
        self.assertEqual(kept_edge["relation"], "được xây dựng năm")
        self.assertEqual(len(kept_edge.get("evidences", [])), 2)
        self.assertEqual(proj["edge_redirects"].get("e_fuzzy_2"), "e_fuzzy_1")

    def test_mark_edge_groups_not_duplicate_protects_independent_historical_events(self) -> None:
        """Kiểm chứng đánh dấu Sự kiện Độc lập (not_duplicate_edge_pairs) ẩn khỏi gợi ý và bảo vệ khỏi gộp tự động."""
        proj = self._create_sample_project()
        suggestions = self.facade.triple_duplicate_suggestions(proj, fuzzy_threshold=0.70)
        exact_grp = next(s for s in suggestions if s["match_type"] == "exact_triplet")

        dis_res = self.facade.mark_edge_groups_not_duplicate_bulk(
            proj,
            [exact_grp],
            note="Hai sự kiện lịch sử khác thời điểm",
        )
        self.assertGreaterEqual(dis_res["added_count"], 1)

        # Không còn xuất hiện trong gợi ý mặc định
        after_suggestions = self.facade.triple_duplicate_suggestions(proj, fuzzy_threshold=0.70, include_dismissed=False)
        self.assertFalse(any(s["match_type"] == "exact_triplet" for s in after_suggestions))

        # Vẫn hiển thị khi bật include_dismissed=True
        with_dismissed = self.facade.triple_duplicate_suggestions(proj, fuzzy_threshold=0.70, include_dismissed=True)
        exact_dis = next(s for s in with_dismissed if s["match_type"] == "exact_triplet")
        self.assertTrue(exact_dis.get("dismissed"))

        # Khi gọi collapse_duplicate_edges toàn cục (selected_groups=None), cặp đã đánh dấu Sự kiện Độc lập được bảo vệ không bị gộp!
        collapse_res = self.facade.collapse_duplicate_edges(proj)
        self.assertEqual(collapse_res.merged_duplicate_edges, 0)
        remaining_ids = {e["id"] for e in proj["edges"]}
        self.assertIn("e_exact_1", remaining_ids)
        self.assertIn("e_exact_2", remaining_ids)

    def test_bump_sync_nonce_and_sync_keyed_value_for_triple_tab(self) -> None:
        """Kiểm chứng bump_sync_nonce hoạt động cả khi truyền nonce_key hoặc dùng giá trị mặc định."""
        fake_store: dict[str, object] = {}
        self.assertEqual(bump_sync_nonce("_triple_dedup_nonce_p1", state_store=fake_store), 1)
        self.assertEqual(bump_sync_nonce("_triple_dedup_nonce_p1", state_store=fake_store), 2)
        self.assertEqual(bump_sync_nonce(state_store=fake_store), 1)
        val = sync_keyed_value("triple_dedup_note_p1", "", ("p1", "rev1", 2), state_store=fake_store)
        self.assertEqual(val, "")


if __name__ == "__main__":
    unittest.main()
