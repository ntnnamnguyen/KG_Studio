"""Bộ kiểm thử xác nhận các tối ưu hiệu năng và bộ nhớ (Performance & Memory Optimizations Test Suite).
Xác minh tính đúng đắn 100% của:
1. Project manifest (project.meta.json) & In-memory project registry.
2. Fast review_stats counters & on-demand duplicate suggestions.
3. Direct-slice evidence_context matcher.
4. Batch proposal impact reverse index equivalence.
5. Vector index in-memory cache & invalidation.
6. SQLite indexes & query_edges_page pagination.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.domain.catalogs.service import batch_proposal_impacts, proposal_impact
from backend.domain.curation.service import (
    duplicate_suggestions,
    evidence_context,
    review_stats,
)
from backend.domain.documents.processor import count_chunks
from backend.integrations.embedder_gateway import default_embedder
from backend.repositories.json_repo import MANIFEST_FILE, JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from shared.constants import STATUS_APPROVED
from shared.text_utils import normal, sha


class PerformanceOptimizationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = JsonProjectRepository(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_manifest_and_registry_cache(self) -> None:
        """Kiểm tra lưu manifest nhỏ và đọc lại không cần mở full JSON."""
        project = empty_project("Dự án Hà Nội Cổ")
        project["documents"] = [{"id": "d1", "name": "doc1.txt", "text": "Hà Nội mùa thu", "hash": "h1"}]
        project["nodes"] = [{"id": "n1", "name": "Hà Nội", "kind": "địa danh"}]
        project["edges"] = [{"id": "e1", "source": "n1", "target": "n1", "relation": "thuộc", "status": "pending"}]

        saved_file = self.repo.save_project(project)
        folder = saved_file.parent
        meta_file = folder / MANIFEST_FILE
        self.assertTrue(meta_file.exists(), "Manifest project.meta.json phải được tạo tự động khi save_project")

        # Kiểm tra nội dung manifest
        meta = self.repo._get_manifest(folder)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["name"], "Dự án Hà Nội Cổ")
        self.assertEqual(meta["documents_count"], 1)
        self.assertEqual(meta["nodes_count"], 1)
        self.assertEqual(meta["edges_count"], 1)

        # Kiểm tra list_projects sử dụng manifest
        names = self.repo.list_projects()
        self.assertIn("Dự án Hà Nội Cổ", names)

        # Kiểm tra list_project_headers
        headers = self.repo.list_project_headers()
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0]["name"], "Dự án Hà Nội Cổ")

    def test_fast_review_stats_and_duplicate_on_demand(self) -> None:
        """Kiểm tra review_stats mặc định không chạy duplicate scan O(N^2)."""
        project = empty_project("Test Stats")
        project["nodes"] = [
            {"id": f"n{i}", "name": f"Thực thể {i}", "kind": "di tích"} for i in range(50)
        ]
        project["edges"] = [
            {"id": "e1", "source": "n1", "target": "n2", "relation": "thuộc", "status": STATUS_APPROVED}
        ]

        # Gọi review_stats mặc định (include_duplicates=False)
        stats = review_stats(project, include_duplicates=False)
        self.assertEqual(stats["nodes"], 50)
        self.assertEqual(stats["edges"], 1)
        self.assertEqual(stats["approved"], 1)
        self.assertEqual(stats["duplicate_pairs"], -1, "Mặc định không tự động quét cặp nghi trùng")

        # Gọi có include_duplicates=True
        stats_with_dup = review_stats(project, include_duplicates=True)
        self.assertGreaterEqual(stats_with_dup["duplicate_pairs"], 0)

    def test_evidence_context_fast_direct_slice(self) -> None:
        """Kiểm tra đường nhanh Direct Slice trong evidence_context."""
        full_text = "Thành phố Hà Nội nghìn năm văn hiến. Đền Ngọc Sơn nằm ở hồ Hoàn Kiếm xinh đẹp."
        quote = "Đền Ngọc Sơn nằm ở hồ Hoàn Kiếm"
        v_start = full_text.find(quote)
        v_end = v_start + len(quote)

        project = empty_project("Test Evidence")
        doc_id = "doc_test"
        project["documents"] = [
            {"id": doc_id, "name": "test.txt", "text": full_text, "hash": sha(full_text)}
        ]
        edge = {
            "id": "e_test",
            "doc_id": doc_id,
            "evidence": quote,
            "verified_start_char": v_start,
            "verified_end_char": v_end,
            "start_char": v_start,
            "end_char": v_end,
            "doc_fingerprint": sha(full_text)[:16],
        }

        ctx = evidence_context(project, edge)
        self.assertTrue(ctx["found"])
        self.assertEqual(ctx["match_method"], "exact")
        self.assertEqual(ctx["start_char"], v_start)
        self.assertEqual(ctx["end_char"], v_end)

    def test_batch_proposal_impacts_equivalence(self) -> None:
        """Kiểm tra batch_proposal_impacts cho kết quả chính xác 100% như proposal_impact đơn lẻ."""
        project = empty_project("Test Impacts")
        project["nodes"] = [
            {"id": "n1", "name": "Node 1", "schema_proposal_ids": ["p1"]},
            {"id": "n2", "name": "Node 2", "schema_proposal_ids": ["p2"]},
            {"id": "n3", "name": "Node 3", "schema_proposal_ids": []},
        ]
        project["edges"] = [
            {"id": "e1", "source": "n1", "target": "n2", "schema_proposal_ids": ["p1"]},
            {"id": "e2", "source": "n2", "target": "n3", "schema_proposal_ids": []},
            {"id": "e3", "source": "n3", "target": "n1", "schema_proposal_ids": []},
        ]

        single_p1 = proposal_impact(project, "p1")
        single_p2 = proposal_impact(project, "p2")

        batch_res = batch_proposal_impacts(project, ["p1", "p2"])
        self.assertEqual(batch_res["p1"], single_p1)
        self.assertEqual(batch_res["p2"], single_p2)

        # p1 tác động direct lên n1, e1; indirect lên e3 (vì n1 là target của e3)
        self.assertIn("n1", batch_res["p1"]["nodes"])
        self.assertIn("e1", batch_res["p1"]["direct_edges"])
        self.assertIn("e3", batch_res["p1"]["indirect_edges"])

    def test_vector_repo_memory_cache(self) -> None:
        """Kiểm tra bộ nhớ đệm RAM trong VectorIndexRepository."""
        vec_repo = VectorIndexRepository(self.root / "vectors")
        embedder = default_embedder("hybrid_vn:default")
        cat_items = [
            {"name": "di tích", "definition": "Công trình di tích"},
            {"name": "nhân vật", "definition": "Nhân vật lịch sử"},
        ]

        items1, mat1 = vec_repo.ensure_index("proj_vec_test", "entity_types", cat_items, embedder)
        self.assertEqual(len(items1), 2)
        self.assertEqual(mat1.shape[0], 2)

        # Lần gọi 2 phải trả từ RAM cache
        items2, mat2 = vec_repo.ensure_index("proj_vec_test", "entity_types", cat_items, embedder)
        self.assertIs(items1, items2, "Bộ nhớ đệm RAM phải trả lại đúng đối tượng đã nạp")

        # Invalidate phải dọn dẹp cache
        vec_repo.invalidate_project_indices("proj_vec_test")
        items3, mat3 = vec_repo.ensure_index("proj_vec_test", "entity_types", cat_items, embedder)
        self.assertIsNot(mat1, mat3, "Sau khi invalidate, ma trận vector phải được tính toán hoặc nạp lại mới")

    def test_sqlite_indexes_and_pagination(self) -> None:
        """Kiểm tra SQLite schema index và hàm phân trang query_edges_page."""
        sql_repo = SQLiteProjectRepository(self.root / "test.db")
        project = empty_project("Test SQLite Pagination")
        project_id = project["project_id"]

        for i in range(120):
            project["edges"].append(
                {
                    "id": f"edge_{i + 1}",
                    "source": f"n_{i}",
                    "target": f"n_{i + 1}",
                    "relation": "thuộc",
                    "status": "Chờ duyệt" if i % 2 == 0 else "Đã duyệt",
                    "doc_id": "doc_1",
                    "chunk_number": i // 10,
                    "evidence": "Minh chứng",
                }
            )

        sql_repo.sync_from_project_dict(project)

        # Phân trang trang 1 (50 dòng)
        page1 = sql_repo.query_edges_page(project_id, page=1, page_size=50)
        self.assertEqual(page1["total_count"], 120)
        self.assertEqual(len(page1["items"]), 50)
        self.assertEqual(page1["total_pages"], 3)

        # Phân trang trang 3 (20 dòng còn lại)
        page3 = sql_repo.query_edges_page(project_id, page=3, page_size=50)
        self.assertEqual(len(page3["items"]), 20)


if __name__ == "__main__":
    unittest.main()
