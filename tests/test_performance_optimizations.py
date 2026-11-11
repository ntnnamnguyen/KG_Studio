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

import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.domain.catalogs.service import (
    apply_proposal_decisions,
    batch_proposal_impacts,
    compute_project_revision,
    decide_proposal,
    preview_proposal_decisions,
    proposal_impact,
)
from backend.domain.curation.entities import clear_duplicate_suggestions_cache
from backend.domain.curation.merge import clear_relation_duplicate_suggestions_cache
from backend.domain.curation.service import (
    build_curation_validation_context,
    duplicate_suggestions,
    evidence_context,
    relation_duplicate_suggestions,
    review_stats,
)
from backend.domain.documents.processor import count_chunks
from backend.facade import KGStudioFacade
from backend.integrations.embedder_gateway import default_embedder
from backend.repositories.json_repo import JOURNAL_FILE, MANIFEST_FILE, JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from frontend.components.curation_table import build_edge_table_rows, filter_and_sort_edges
from shared.constants import STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING
from shared.schemas.edc import BulkReviewRequestDTO, ProposalDecisionDTO
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

    def test_batch_apply_proposal_decisions_parity_and_immutability(self) -> None:
        """Kiểm tra duyệt hàng loạt EDC một lượt (single-pass) khớp 100% với duyệt tuần tự."""
        base = empty_project("Test Batch EDC Parity")
        base["relations"] = ["thuộc về"]
        base["relation_notes"] = {"thuộc về": {"definition": "Quan hệ trực thuộc hành chính"}}
        base["entity_types"] = [{"name": "địa danh", "definition": "Khu vực địa lý"}]
        base["documents"] = [{"id": "d1", "name": "d1.txt", "text": "Văn Miếu nằm tại Đống Đa.", "hash": sha("Văn Miếu nằm tại Đống Đa.")}]
        base["schema_proposals"] = [
            {"id": "pr_app", "kind": "relations", "name": "tọa lạc tại", "definition": "Vị trí tọa lạc", "status": "pending", "observations": []},
            {"id": "pr_mrg", "kind": "relations", "name": "trực thuộc", "definition": "Thuộc quyền quản lý", "status": "pending", "observations": []},
            {"id": "pr_rej", "kind": "relations", "name": "quan hệ nhiễu", "definition": "Nhiễu", "status": "pending", "observations": []},
        ]
        base["nodes"] = [
            {"id": "n1", "name": "Văn Miếu", "kind": "địa danh", "schema_proposal_ids": []},
            {"id": "n2", "name": "Đống Đa", "kind": "địa danh", "schema_proposal_ids": []},
        ]
        base["edges"] = [
            {"id": "e1", "source": "n1", "target": "n2", "relation": "tọa lạc tại", "status": STATUS_PENDING, "schema_proposal_ids": ["pr_app"]},
            {"id": "e2", "source": "n1", "target": "n2", "relation": "trực thuộc", "status": STATUS_APPROVED, "schema_proposal_ids": ["pr_mrg"]},
            {"id": "e3", "source": "n1", "target": "n2", "relation": "quan hệ nhiễu", "status": STATUS_APPROVED, "schema_proposal_ids": ["pr_rej"]},
        ]

        proj_seq = copy.deepcopy(base)
        decide_proposal(proj_seq, "pr_app", "approve", canonical_name="tọa lạc tại", definition="Vị trí tọa lạc")
        decide_proposal(proj_seq, "pr_mrg", "merge", canonical_name="thuộc về", definition="Thuộc quyền quản lý")
        decide_proposal(proj_seq, "pr_rej", "reject", note="Loại bỏ")

        proj_orig = copy.deepcopy(base)
        req = BulkReviewRequestDTO(
            project_id=proj_orig["project_id"],
            kind="relations",
            expected_revision=compute_project_revision(proj_orig),
            request_id="req_parity_1",
            decisions=[
                ProposalDecisionDTO(proposal_id="pr_app", kind="relations", action="approve", canonical_name="tọa lạc tại", definition="Vị trí tọa lạc"),
                ProposalDecisionDTO(proposal_id="pr_mrg", kind="relations", action="merge", canonical_name="thuộc về", definition="Thuộc quyền quản lý"),
                ProposalDecisionDTO(proposal_id="pr_rej", kind="relations", action="reject", note="Loại bỏ"),
            ],
        )
        preview = preview_proposal_decisions(proj_orig, req)
        self.assertEqual(preview.valid_count, 3)
        proj_batch, res = apply_proposal_decisions(proj_orig, req, preview=preview, mutate_in_place=False)

        self.assertEqual(res.applied_count, 3)
        # Đảm bảo đầu vào không bị đột biến khi mutate_in_place=False
        self.assertEqual(proj_orig["edges"][1]["relation"], "trực thuộc")
        self.assertEqual(proj_orig["schema_proposals"][0]["status"], "pending")

        # Đảm bảo đồ thị và danh mục sau xử lý lô khớp hoàn toàn với tuần tự
        self.assertEqual(proj_batch["nodes"], proj_seq["nodes"])
        self.assertEqual(proj_batch["edges"], proj_seq["edges"])
        self.assertEqual(proj_batch["relations"], proj_seq["relations"])
        for pb, ps in zip(proj_batch["schema_proposals"], proj_seq["schema_proposals"]):
            self.assertEqual(pb["status"], ps["status"])
            self.assertEqual(pb.get("canonical_name", ""), ps.get("canonical_name", ""))

    def test_evidence_context_chunk_fast_path_and_no_snippets(self) -> None:
        """Kiểm tra đường nhanh phạm vi chunk (start_char..end_char) và chế độ include_snippets=False."""
        prefix = "Đoạn mở đầu dài. " * 400
        chunk_body = "Khu vực đầu đoạn. Chùa Một Cột được xây dựng năm 1049 thời Lý Thái Tông. Khu vực cuối đoạn."
        suffix = " Đoạn kết thúc dài." * 400
        full_text = prefix + chunk_body + suffix
        chunk_start = len(prefix)
        chunk_end = chunk_start + len(chunk_body)
        quote = "Chùa Một Cột được xây dựng năm 1049"

        project = empty_project("Test Chunk Fast Path")
        project["documents"] = [{"id": "d_big", "name": "big.txt", "text": full_text, "hash": sha(full_text)}]
        edge = {
            "id": "e_chunk",
            "doc_id": "d_big",
            "evidence": quote,
            "start_char": chunk_start,
            "end_char": chunk_end,
            "doc_fingerprint": sha(full_text)[:16],
        }

        val_ctx = build_curation_validation_context(project)
        full_ctx = evidence_context(project, edge)
        fast_ctx = evidence_context(project, edge, precomputed=val_ctx, include_snippets=False)

        self.assertTrue(fast_ctx["found"])
        self.assertEqual(fast_ctx["match_method"], full_ctx["match_method"])
        self.assertEqual(fast_ctx["match_label"], full_ctx["match_label"])
        self.assertEqual(fast_ctx["start_char"], full_ctx["start_char"])
        self.assertEqual(fast_ctx["end_char"], full_ctx["end_char"])
        self.assertFalse(fast_ctx["ambiguous"])
        self.assertEqual(fast_ctx["text"], "")

        # Kiểm tra trường hợp trích dẫn lặp lại 2 lần ngay trong cùng 1 chunk -> phải báo ambiguous=True
        dup_chunk = "Hồ Gươm rất đẹp. Hồ Gươm rất đẹp."
        dup_text = prefix + dup_chunk + suffix
        project["documents"][0] = {"id": "d_big", "name": "big.txt", "text": dup_text, "hash": sha(dup_text)}
        dup_edge = {
            "id": "e_amb",
            "doc_id": "d_big",
            "evidence": "Hồ Gươm rất đẹp.",
            "start_char": len(prefix),
            "end_char": len(prefix) + len(dup_chunk),
            "doc_fingerprint": sha(dup_text)[:16],
        }
        val_ctx_dup = build_curation_validation_context(project)
        amb_ctx = evidence_context(project, dup_edge, precomputed=val_ctx_dup, include_snippets=False)
        self.assertTrue(amb_ctx["found"])
        self.assertTrue(amb_ctx["ambiguous"])

    def test_curation_filter_sort_and_table_rows_with_precomputed_context(self) -> None:
        """Kiểm tra filter_and_sort_edges và build_edge_table_rows với proposals_by_kind_norm O(1)."""
        txt = "Hoàng thành Thăng Long nằm tại quận Ba Đình."
        project = empty_project("Test UI Filter Sort")
        project["entity_types"] = [{"name": "di tích", "definition": "Di tích"}, {"name": "quận", "definition": "Quận"}]
        project["relations"] = ["nằm tại"]
        project["relation_notes"] = {"nằm tại": {"definition": "Vị trí"}}
        project["schema_proposals"] = [
            {"id": "p_pend", "kind": "relations", "name": "thuộc địa phận", "status": "pending"}
        ]
        project["documents"] = [{"id": "d1", "name": "tl.txt", "text": txt, "hash": sha(txt)}]
        project["nodes"] = [
            {"id": "n1", "name": "Hoàng thành Thăng Long", "kind": "di tích"},
            {"id": "n2", "name": "Ba Đình", "kind": "quận"},
        ]
        project["edges"] = [
            {
                "id": "e_valid",
                "source": "n1",
                "target": "n2",
                "relation": "nằm tại",
                "evidence": txt,
                "doc_id": "d1",
                "start_char": 0,
                "end_char": len(txt),
                "doc_fingerprint": sha(txt)[:16],
                "status": STATUS_PENDING,
            },
            {
                "id": "e_pending_prop",
                "source": "n1",
                "target": "n2",
                "relation": "thuộc địa phận",
                "evidence": "Câu không tồn tại",
                "doc_id": "d1",
                "status": STATUS_CHECK,
            },
        ]

        sorted_edges = filter_and_sort_edges(project, {"sort_by": "priority"})
        self.assertEqual([e["id"] for e in sorted_edges], ["e_pending_prop", "e_valid"])

        only_pending_schema = filter_and_sort_edges(project, {"schema_state": "pending_proposal"})
        self.assertEqual([e["id"] for e in only_pending_schema], ["e_pending_prop"])

        rows = build_edge_table_rows(project, sorted_edges, {"e_valid"})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["schema_status_code"], "pending_proposal")
        self.assertEqual(rows[1]["schema_status_code"], "valid")
        self.assertTrue(rows[1]["selected"])

    def test_relation_duplicate_suggestions_candidate_blocking_large_scale(self) -> None:
        """Kiểm tra thuật toán lọc ứng viên (candidate blocking) khi số quan hệ >= 120 không bỏ sót cặp trùng."""
        clear_relation_duplicate_suggestions_cache()
        project = empty_project("Test Relation Blocking")
        edges = []
        # Tạo 135 quan hệ phân biệt hoàn toàn để kích hoạt nhánh n_rels >= 120
        for idx in range(135):
            edges.append(
                {
                    "id": f"ef_{idx}",
                    "source": "n1",
                    "target": "n2",
                    "relation": f"khái_niệm_riêng_biệt_{idx:03d}_alpha_{idx * 7}",
                }
            )
        # Cấy 4 cặp trùng đặc trưng cho 4 tiêu chí: exact clean, substring, jaccard >= 0.65, fuzzy >= 0.80
        planted = [
            ("tọa_lạc_ở", "tọa lạc ở"),
            ("nằm ở khu vực trung tâm", "nằm ở khu vực trung tâm lịch sử"),
            ("thuộc địa bàn quản lý quận", "quận thuộc địa bàn quản lý"),
            ("được khởi công xây dựng năm", "được khởi công xây dựng năn"),
        ]
        for p_idx, (ra, rb) in enumerate(planted):
            edges.append({"id": f"ep_a_{p_idx}", "source": "n1", "target": "n2", "relation": ra})
            edges.append({"id": f"ep_b_{p_idx}", "source": "n1", "target": "n2", "relation": rb})
        project["edges"] = edges

        sugs = relation_duplicate_suggestions(project, fuzzy_threshold=0.75)
        found_pairs = {tuple(sorted([s["relation_a"], s["relation_b"]])) for s in sugs}
        for ra, rb in planted:
            self.assertIn(tuple(sorted([ra, rb])), found_pairs, f"Không được bỏ sót cặp quan hệ trùng ({ra}, {rb})")

    def test_bulk_not_duplicate_and_journal_v2_backup_recovery(self) -> None:
        """Kiểm tra đánh dấu hàng loạt Khác đối tượng / Khác quan hệ (lưu 1 lần) và khôi phục journal v2."""
        clear_duplicate_suggestions_cache()
        clear_relation_duplicate_suggestions_cache()
        facade = KGStudioFacade(
            json_repo=JsonProjectRepository(self.root / "projects"),
            sqlite_repo=SQLiteProjectRepository(self.root / "test_bulk.db"),
            vector_repo=VectorIndexRepository(self.root / "vectors_bulk"),
        )
        project = empty_project("Bulk Dismiss Project")
        project["nodes"] = [
            {"id": "n1", "name": "Hồ Hoàn Kiếm", "kind": "địa danh"},
            {"id": "n2", "name": "Hồ Hoàn Kiếm ", "kind": "địa danh"},
            {"id": "n3", "name": "Đền Ngọc Sơn", "kind": "di tích"},
            {"id": "n4", "name": "Đền Ngọc Sơn ", "kind": "di tích"},
        ]
        project["edges"] = [
            {"id": "e1", "source": "n1", "target": "n3", "relation": "tọa_lạc_tại"},
            {"id": "e2", "source": "n2", "target": "n4", "relation": "tọa lạc tại"},
        ]
        facade.save_project(project)

        ent_res = facade.mark_pairs_not_duplicate_bulk(project, [("n1", "n2"), ("n3", "n4")], note="Bulk test")
        self.assertEqual(len(ent_res), 2)
        self.assertEqual(duplicate_suggestions(project), [])

        rel_res = facade.mark_relation_pairs_not_duplicate_bulk(project, [("tọa_lạc_tại", "tọa lạc tại")], note="Bulk rel")
        self.assertEqual(rel_res["added_count"], 1)
        self.assertEqual(relation_duplicate_suggestions(project), [])

        # Kiểm tra cơ chế khôi phục tự động journal v2 từ file backup .project.json.journal.bak khi load_project
        folder = facade.json_repo.project_dir(project["name"])
        target_json = folder / "project.json"
        bak_name = ".project.json.journal.bak"
        bak_json = folder / bak_name
        good_bytes = target_json.read_bytes()
        bak_json.write_bytes(good_bytes)
        target_json.write_text("{corrupted_partial_write", encoding="utf-8")
        (folder / JOURNAL_FILE).write_text(
            json.dumps(
                {
                    "version": 2,
                    "files": {
                        "project.json": {
                            "existed": True,
                            "bak": bak_name,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        reloaded = facade.json_repo.load_project(project["name"])
        self.assertFalse((folder / JOURNAL_FILE).exists())
        self.assertFalse(bak_json.exists())
        self.assertEqual(len(reloaded["not_duplicate_pairs"]), 2)


if __name__ == "__main__":
    unittest.main()
