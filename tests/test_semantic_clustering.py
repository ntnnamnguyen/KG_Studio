"""Unit tests cho tính năng Quét & Gom cụm ngữ nghĩa AI (DeepSeek Semantic Clustering)."""
import unittest
from unittest.mock import MagicMock, patch

from backend.domain.curation.semantic_clustering import (
    apply_semantic_clusters,
    build_clustering_prompt,
    bulk_apply_entity_type_merges,
    collect_cluster_items,
    preview_clustering_prompt,
    scan_semantic_clusters,
)
from backend.facade import KGStudioFacade
from frontend.client import FrontendClient


class TestSemanticClustering(unittest.TestCase):
    def setUp(self):
        self.sample_project = {
            "name": "TestClustering",
            "project_id": "test_clustering_p1",
            "nodes": [
                {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích lịch sử"},
                {"id": "n2", "name": "Đền Quán Thánh", "kind": "di tích văn hóa"},
                {"id": "n3", "name": "Nhà hát Lớn", "kind": "công trình kiến trúc"},
                {"id": "n4", "name": "Hà Nội", "kind": "địa danh"},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "Chùa Một Cột",
                    "relation": "tọa lạc tại",
                    "target": "Hà Nội",
                    "evidence": "Chùa Một Cột tọa lạc tại Hà Nội",
                    "status": "Chờ duyệt",
                },
                {
                    "id": "e2",
                    "source": "Đền Quán Thánh",
                    "relation": "nằm ở",
                    "target": "Hà Nội",
                    "evidence": "Đền Quán Thánh nằm ở Hà Nội",
                    "status": "Chờ duyệt",
                },
                {
                    "id": "e3",
                    "source": "Nhà hát Lớn",
                    "relation": "có địa chỉ tại",
                    "target": "Hà Nội",
                    "evidence": "Nhà hát Lớn có địa chỉ tại Hà Nội",
                    "status": "Chờ duyệt",
                },
            ],
            "relation_types": [
                {"name": "nằm tại", "definition": "Vị trí địa lý tại một nơi", "aliases": []}
            ],
            "relations": ["nằm tại"],
            "entity_types": [
                {"name": "di tích", "definition": "Công trình lịch sử văn hóa", "aliases": []},
                {"name": "địa danh", "definition": "Địa điểm địa lý", "aliases": []},
            ],
            "schema_proposals": [
                {
                    "id": "prop_rel_1",
                    "kind": "relations",
                    "name": "tọa lạc tại",
                    "definition": "Vị trí ở nơi nào đó",
                    "status": "pending",
                },
                {
                    "id": "prop_kind_1",
                    "kind": "entity_types",
                    "name": "di tích lịch sử",
                    "definition": "Di tích có ý nghĩa lịch sử",
                    "status": "pending",
                },
            ],
        }

    def test_collect_cluster_items_relations(self):
        items = collect_cluster_items(self.sample_project, kind="relations")
        self.assertGreaterEqual(len(items), 3)
        names = [it["name"] for it in items]
        self.assertIn("tọa lạc tại", names)
        self.assertIn("nằm ở", names)
        self.assertIn("có địa chỉ tại", names)
        self.assertIn("nằm tại", names)

        toa_lac = next(it for it in items if it["name"] == "tọa lạc tại")
        self.assertEqual(toa_lac["count"], 1)
        self.assertTrue(len(toa_lac["sample_evidences"]) > 0)

        nam_tai = next(it for it in items if it["name"] == "nằm tại")
        self.assertTrue(nam_tai["in_catalog"])

    def test_collect_cluster_items_entity_types(self):
        items = collect_cluster_items(self.sample_project, kind="entity_types")
        self.assertGreaterEqual(len(items), 3)
        names = [it["name"] for it in items]
        self.assertIn("di tích lịch sử", names)
        self.assertIn("di tích văn hóa", names)
        self.assertIn("công trình kiến trúc", names)
        self.assertIn("di tích", names)

        dt_ls = next(it for it in items if it["name"] == "di tích lịch sử")
        self.assertEqual(dt_ls["count"], 1)
        self.assertIn("Chùa Một Cột", dt_ls["sample_nodes"])

    def test_build_clustering_prompt(self):
        rel_items = collect_cluster_items(self.sample_project, kind="relations")
        prompt = build_clustering_prompt(rel_items, kind="relations")
        self.assertIn("tọa lạc tại", prompt)
        self.assertIn("nằm tại", prompt)
        self.assertIn("canonical_name", prompt)
        self.assertIn("synonyms", prompt)

    def test_build_clustering_prompt_with_custom_instructions(self):
        rel_items = collect_cluster_items(self.sample_project, kind="relations")
        custom_rule = "Chỉ gom các quan hệ vị trí địa lý, không gộp quan hệ thời gian."
        prompt = build_clustering_prompt(rel_items, kind="relations", custom_instructions=custom_rule)
        self.assertIn(custom_rule, prompt)
        self.assertIn("CHỈ DẪN & QUY TẮC ĐẶC BIỆT CỦA CHUYÊN GIA", prompt)

    def test_preview_clustering_prompt(self):
        prompt_rel = preview_clustering_prompt(self.sample_project, kind="relations", custom_instructions="Quy tắc riêng")
        self.assertIn("Quy tắc riêng", prompt_rel)
        self.assertIn("tọa lạc tại", prompt_rel)

        prompt_type = preview_clustering_prompt(self.sample_project, kind="entity_types", custom_instructions="Gom di tích")
        self.assertIn("Gom di tích", prompt_type)
        self.assertIn("di tích lịch sử", prompt_type)

    @patch("backend.domain.curation.semantic_clustering.make_adapter")
    def test_scan_semantic_clusters_mock_llm(self, mock_make_adapter):
        mock_adapter = MagicMock()
        mock_adapter.chat.return_value = MagicMock(
            content='{"clusters": [{"canonical_name": "nằm tại", "synonyms": ["tọa lạc tại", "nằm ở", "có địa chỉ tại"], "reason": "Đều chỉ vị trí địa lý"}]}',
            input_tokens=150,
            output_tokens=40,
        )
        mock_make_adapter.return_value = mock_adapter

        res = scan_semantic_clusters(
            self.sample_project,
            kind="relations",
            provider="DeepSeek",
            api_key="sk-test",
            model="deepseek-chat",
        )

        self.assertEqual(res["clusters_count"], 1)
        cluster = res["clusters"][0]
        self.assertEqual(cluster["canonical_name"], "nằm tại")
        self.assertEqual(set(cluster["synonyms"]), {"tọa lạc tại", "nằm ở", "có địa chỉ tại"})
        self.assertEqual(cluster["affected_count"], 3)
        self.assertIn("vị trí địa lý", cluster["reason"])

    def test_apply_semantic_clusters_relations(self):
        approved = [
            {
                "id": "c1",
                "canonical_name": "nằm tại",
                "synonyms": ["tọa lạc tại", "nằm ở", "có địa chỉ tại"],
                "reason": "Vị trí địa lý",
            }
        ]
        proj, result = apply_semantic_clusters(
            self.sample_project,
            kind="relations",
            approved_clusters=approved,
            collapse_duplicate_edges=True,
        )

        self.assertEqual(result.status, "applied")
        for edge in proj["edges"]:
            self.assertEqual(edge["relation"], "nằm tại")

        # Cả 3 cạnh ban đầu đều có nguồn là Chùa Một Cột, Đền Quán Thánh, Nhà hát Lớn đến Hà Nội.
        # Nhưng nếu e1 và e2 có cùng nguồn và đích, chúng sẽ bị gộp nếu collapse_duplicate_edges=True
        # Kiểm tra aliases
        self.assertIn("tọa lạc tại", proj["relation_aliases"]["nằm tại"])
        self.assertIn("nằm ở", proj["relation_aliases"]["nằm tại"])

        # Kiểm tra catalog
        cat_names = [r["name"] for r in proj["relation_types"]]
        self.assertIn("nằm tại", cat_names)
        self.assertNotIn("tọa lạc tại", cat_names)

        # Kiểm tra proposals
        p_rel = next(p for p in proj["schema_proposals"] if p["id"] == "prop_rel_1")
        self.assertEqual(p_rel["status"], "merged")
        self.assertEqual(p_rel["canonical_name"], "nằm tại")

    def test_apply_semantic_clusters_entity_types(self):
        approved = [
            {
                "id": "c_type_1",
                "canonical_name": "di tích",
                "synonyms": ["di tích lịch sử", "di tích văn hóa", "công trình kiến trúc"],
                "reason": "Đều là di tích công trình",
            }
        ]
        proj, result = apply_semantic_clusters(
            self.sample_project,
            kind="entity_types",
            approved_clusters=approved,
        )

        self.assertEqual(result.status, "success")
        nodes_by_id = {n["id"]: n for n in proj["nodes"]}
        self.assertEqual(nodes_by_id["n1"]["kind"], "di tích")
        self.assertEqual(nodes_by_id["n2"]["kind"], "di tích")
        self.assertEqual(nodes_by_id["n3"]["kind"], "di tích")
        self.assertEqual(nodes_by_id["n4"]["kind"], "địa danh")  # Không đổi

        # Aliases và Catalog
        self.assertIn("di tích lịch sử", proj["entity_type_aliases"]["di tích"])
        type_names = [t["name"] if isinstance(t, dict) else t for t in proj["entity_types"]]
        self.assertIn("di tích", type_names)
        self.assertNotIn("di tích lịch sử", type_names)

        # Proposal
        p_kind = next(p for p in proj["schema_proposals"] if p["id"] == "prop_kind_1")
        self.assertEqual(p_kind["status"], "merged")
        self.assertEqual(p_kind["canonical_name"], "di tích")

    def test_facade_and_client_integration(self):
        import tempfile
        from pathlib import Path
        from backend.repositories.json_repo import JsonProjectRepository
        from backend.repositories.sqlite_repo import SQLiteProjectRepository
        from backend.repositories.vector_repo import VectorIndexRepository

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            facade = KGStudioFacade(
                json_repo=JsonProjectRepository(tmp_path / "projects"),
                sqlite_repo=SQLiteProjectRepository(tmp_path / "test.db"),
                vector_repo=VectorIndexRepository(tmp_path / "vectors"),
            )
            client = FrontendClient(facade=facade)

        # Test preview clustering prompt
        prev_prompt = client.preview_clustering_prompt(
            self.sample_project, kind="relations", custom_instructions="Ưu tiên tên ngắn"
        )
        self.assertIn("Ưu tiên tên ngắn", prev_prompt)

        # Test scan with mock
        with patch("backend.domain.curation.semantic_clustering.make_adapter") as mock_adapter_call:
            mock_inst = MagicMock()
            mock_inst.chat.return_value = MagicMock(
                content='{"clusters": [{"canonical_name": "nằm tại", "synonyms": ["tọa lạc tại"], "reason": "Đồng nghĩa"}]}',
                input_tokens=50,
                output_tokens=20,
            )
            mock_adapter_call.return_value = mock_inst

            scan_res = client.scan_semantic_clusters(
                self.sample_project,
                kind="relations",
                provider="DeepSeek",
                api_key="sk-test",
            )
            self.assertEqual(scan_res["clusters_count"], 1)

        # Test apply through client
        res = client.apply_semantic_clusters(
            self.sample_project,
            kind="relations",
            approved_clusters=scan_res["clusters"],
        )
        self.assertGreaterEqual(res.applied_count, 1)

    @patch("backend.domain.curation.semantic_clustering.make_adapter")
    def test_diacritic_and_underscore_resolution(self, mock_make_adapter):
        """Kiểm tra khi đồ thị lưu dạng không dấu gạch dưới (toa_lac_tai) nhưng DeepSeek trả về tiếng Việt có dấu (tọa lạc tại)."""
        project = {
            "name": "TestDiacritics",
            "nodes": [
                {"id": "n1", "name": "A", "kind": "di tích"},
                {"id": "n2", "name": "B", "kind": "địa danh"},
            ],
            "edges": [
                {"id": "e1", "source": "A", "relation": "toa_lac_tai", "target": "B"},
                {"id": "e2", "source": "A", "relation": "nam_o", "target": "B"},
                {"id": "e3", "source": "A", "relation": "dat_tai", "target": "B"},
            ],
            "relation_types": [
                {"name": "toa_lac_tai", "definition": "Vị trí"}
            ],
        }

        mock_adapter = MagicMock()
        # DeepSeek trả về tên có dấu và khoảng trắng
        mock_adapter.chat.return_value = MagicMock(
            content='{"clusters": [{"canonical_name": "tọa lạc tại", "synonyms": ["nằm ở", "đặt tại"], "reason": "Chỉ vị trí địa lý"}]}',
            input_tokens=100,
            output_tokens=50,
        )
        mock_make_adapter.return_value = mock_adapter

        res = scan_semantic_clusters(project, kind="relations", scope="top_50", api_key="sk-test")
        self.assertEqual(res["clusters_count"], 1)
        c = res["clusters"][0]
        # Canonical name được map chuẩn về toa_lac_tai trong đồ thị
        self.assertEqual(c["canonical_name"], "toa_lac_tai")
        # Các từ đồng nghĩa có dấu được map chuẩn về nam_o và dat_tai trong đồ thị
        self.assertIn("nam_o", c["synonyms"])
        self.assertIn("dat_tai", c["synonyms"])
        self.assertEqual(c["affected_count"], 2)

    def test_parse_clusters_json_robustness(self):
        """Kiểm tra parse JSON khi LLM trả về markdown fences, trailing commas, hoặc bị cắt cụt (truncated)."""
        from backend.domain.curation.semantic_clustering import _parse_clusters_json

        # 1. Truncated mid-JSON
        truncated = """```json
{
  "clusters": [
    {
      "canonical_name": "toa_lac_tai",
      "synonyms": ["nam_o", "an_vi_tai"],
      "reason": "Vị trí địa lý"
    },
    {
      "canonical_name": "xay_dung",
      "synonyms": ["khoi_cong"
"""
        parsed = _parse_clusters_json(truncated)
        self.assertEqual(len(parsed.get("clusters", [])), 1)
        self.assertEqual(parsed["clusters"][0]["canonical_name"], "toa_lac_tai")

        # 2. Trailing comma
        trailing = '{"clusters": [{"canonical_name": "a", "synonyms": ["b"], "reason": "test"}, ]}'
        parsed2 = _parse_clusters_json(trailing)
        self.assertEqual(len(parsed2.get("clusters", [])), 1)

    def test_collect_cluster_items_scope_filtering(self):
        """Kiểm tra bộ lọc phạm vi scope (top_50, freq_ge_2, all)."""
        project = {
            "name": "ScopeTest",
            "nodes": [],
            "edges": [
                {"id": f"e{i}", "source": "A", "relation": f"rel_{i%10}", "target": "B"}
                for i in range(100)
            ] + [
                {"id": "e_single", "source": "A", "relation": "rare_rel", "target": "B"}
            ],
            "relation_types": [],
        }

        all_items = collect_cluster_items(project, "relations", scope="all")
        self.assertEqual(len(all_items), 11)  # rel_0..rel_9 + rare_rel

        top5 = collect_cluster_items(project, "relations", scope="top_50")[:5]
        self.assertEqual(len(top5), 5)

        freq2 = collect_cluster_items(project, "relations", scope="freq_ge_2")
        freq2_names = [it["name"] for it in freq2]
        self.assertNotIn("rare_rel", freq2_names)
        self.assertEqual(len(freq2), 10)


if __name__ == "__main__":
    unittest.main()


