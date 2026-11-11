"""Bộ kiểm thử đơn vị toàn diện cho mô-đun G-Retriever (PCST), HippoRAG (PPR) & Benchmark Thực nghiệm."""
from __future__ import annotations

import unittest
from typing import Any

from backend.domain.graph.service import approved_json_bytes, export_zip
from backend.domain.graph.g_retriever import (
    answer_question_with_graph,
    evaluate_retrieval_methods,
    generate_qa_benchmark,
    load_project_from_export_bytes,
    retrieve_subgraph,
)
from backend.facade import get_facade
from frontend.client import FrontendClient


class _DummyLLMClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def chat_text(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.reply


def _make_sample_hanoi_project() -> dict[str, Any]:
    """Tạo đồ thị mẫu có cả cầu nối 2-hop chuyên biệt lẫn siêu đỉnh Hub ('Hà Nội') gây nhiễu."""
    nodes = [
        {
            "id": "n_hub_hn",
            "name": "Hà Nội",
            "kind": "Địa danh",
            "description": "Thủ đô của Việt Nam.",
            "aliases": ["Thăng Long"],
        },
        {
            "id": "n_chua_mot_cot",
            "name": "Chùa Một Cột",
            "kind": "Di tích",
            "description": "Ngôi chùa có kiến trúc hình bông sen độc đáo.",
            "aliases": ["Diên Hựu tự"],
        },
        {
            "id": "n_ly_thai_tong",
            "name": "Lý Thái Tông",
            "kind": "Nhân vật",
            "description": "Vị vua thứ hai của triều đại nhà Lý.",
            "aliases": ["Lý Phật Mã"],
        },
        {
            "id": "n_nha_ly",
            "name": "Triều đại nhà Lý",
            "kind": "Tổ chức",
            "description": "Triều đại phong kiến mở đầu thời kỳ hưng thịnh tại Thăng Long.",
            "aliases": ["Nhà Lý"],
        },
        {
            "id": "n_nam_1049",
            "name": "năm 1049",
            "kind": "Thời gian",
            "description": "Năm khởi dựng Chùa Một Cột.",
            "aliases": [],
        },
    ]
    # Tạo thêm 25 đỉnh vệ tinh nối vào 'Hà Nội' để biến 'Hà Nội' thành đỉnh Hub bậc cao
    for i in range(1, 26):
        nodes.append(
            {
                "id": f"n_sat_{i}",
                "name": f"Địa điểm vệ tinh {i}",
                "kind": "Địa danh",
                "description": f"Địa điểm thứ {i} thuộc Hà Nội.",
                "aliases": [],
            }
        )

    edges = [
        {
            "id": "e_cmc_ltt",
            "source": "n_chua_mot_cot",
            "relation": "được xây dựng dưới triều vua",
            "target": "n_ly_thai_tong",
            "status": "Đã duyệt",
            "confidence": 0.95,
            "evidence": "Chùa Một Cột được xây dựng dưới triều vua Lý Thái Tông.",
            "doc_id": "d1",
            "doc_name": "di_tich_ha_noi.txt",
        },
        {
            "id": "e_ltt_nhaly",
            "source": "n_ly_thai_tong",
            "relation": "thuộc vương triều",
            "target": "n_nha_ly",
            "status": "Đã duyệt",
            "confidence": 0.96,
            "evidence": "Vua Lý Thái Tông thuộc vương triều nhà Lý.",
            "doc_id": "d1",
            "doc_name": "di_tich_ha_noi.txt",
        },
        {
            "id": "e_cmc_1049",
            "source": "n_chua_mot_cot",
            "relation": "khởi dựng vào",
            "target": "n_nam_1049",
            "status": "Đã duyệt",
            "confidence": 0.92,
            "evidence": "Chùa Một Cột khởi dựng vào mùa đông năm 1049.",
            "doc_id": "d1",
            "doc_name": "di_tich_ha_noi.txt",
        },
        {
            "id": "e_cmc_hn",
            "source": "n_chua_mot_cot",
            "relation": "tọa lạc tại",
            "target": "n_hub_hn",
            "status": "Đã duyệt",
            "confidence": 0.90,
            "evidence": "Chùa Một Cột tọa lạc tại Hà Nội.",
            "doc_id": "d1",
            "doc_name": "di_tich_ha_noi.txt",
        },
    ]
    for i in range(1, 26):
        edges.append(
            {
                "id": f"e_hub_{i}",
                "source": f"n_sat_{i}",
                "relation": "trực thuộc",
                "target": "n_hub_hn",
                "status": "Đã duyệt",
                "confidence": 0.80,
                "evidence": f"Địa điểm vệ tinh {i} trực thuộc Hà Nội.",
                "doc_id": "d2",
                "doc_name": "hanh_chinh.txt",
            }
        )

    for e in edges:
        e["override"] = True
        e["review_note"] = "Đã kiểm duyệt phục vụ kiểm thử G-Retriever."

    return {
        "project_id": "test_g_retriever_proj",
        "name": "Hanoi GraphRAG Test",
        "saved_at": "2026-11-08T16:00:00",
        "entity_types": ["Địa danh", "Di tích", "Nhân vật", "Tổ chức", "Thời gian"],
        "relations": ["được xây dựng dưới triều vua", "thuộc vương triều", "khởi dựng vào", "tọa lạc tại", "trực thuộc"],
        "documents": [
            {"id": "d1", "name": "di_tich_ha_noi.txt", "text": "Chùa Một Cột được xây dựng dưới triều vua Lý Thái Tông. Vua Lý Thái Tông thuộc vương triều nhà Lý. Chùa Một Cột khởi dựng vào mùa đông năm 1049. Chùa Một Cột tọa lạc tại Hà Nội."},
            {"id": "d2", "name": "hanh_chinh.txt", "text": "Các địa điểm vệ tinh trực thuộc Hà Nội."},
        ],
        "nodes": nodes,
        "edges": edges,
        "runs": [],
    }


class TestGRetrieverModule(unittest.TestCase):
    def setUp(self) -> None:
        self.project = _make_sample_hanoi_project()

    def test_pcst_two_hop_bridge_and_leaf_expansion(self) -> None:
        question = (
            "Thực thể có quan hệ 'được xây dựng dưới triều vua' với 'Chùa Một Cột' "
            "có quan hệ 'thuộc vương triều' với thực thể nào?"
        )
        res = retrieve_subgraph(
            self.project,
            question,
            method="pcst",
            max_edges=8,
            expand_leaf_attributes=True,
        )
        node_ids = {n["id"] for n in res["subgraph_nodes"]}
        edge_ids = {e["id"] for e in res["subgraph_edges"]}

        # Đảm bảo thu hồi đủ hạt giống (Chùa Một Cột), cầu nối (Lý Thái Tông) và đáp án đích 2-hop (Triều đại nhà Lý)
        self.assertIn("n_chua_mot_cot", node_ids)
        self.assertIn("n_ly_thai_tong", node_ids)
        self.assertIn("n_nha_ly", node_ids)
        self.assertIn("e_cmc_ltt", edge_ids)
        self.assertIn("e_ltt_nhaly", edge_ids)
        # Mở rộng 1-hop thuộc tính Thời gian ('năm 1049')
        self.assertIn("n_nam_1049", node_ids)
        self.assertGreaterEqual(res["largest_component_ratio"], 0.8)
        self.assertIn("=== BẢNG THỰC THỂ TRONG ĐỒ THỊ CON (NODES) ===", res["textualized_prompt"])
        self.assertIn("=== BẢNG QUAN HỆ & BẰNG CHỨNG NGUYÊN VĂN (EDGES) ===", res["textualized_prompt"])

    def test_ppr_and_naive_topk_methods(self) -> None:
        question = "Chùa Một Cột được xây dựng dưới triều vua nào và khởi dựng vào năm nào?"
        res_ppr = retrieve_subgraph(self.project, question, method="ppr", max_edges=6)
        res_naive = retrieve_subgraph(self.project, question, method="naive_topk", max_edges=6)

        self.assertEqual(res_ppr["method"], "ppr")
        self.assertEqual(res_naive["method"], "naive_topk")
        self.assertTrue(any(e["id"] == "e_cmc_ltt" for e in res_ppr["subgraph_edges"]))
        self.assertTrue(any(e["id"] == "e_cmc_1049" for e in res_naive["subgraph_edges"]))

    def test_load_project_from_exported_zip_and_json_bytes(self) -> None:
        import io
        import zipfile

        zip_bytes = export_zip(self.project)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
            self.assertIn("bo_cau_hoi_g_retriever.json", names)
            self.assertIn("bo_cau_hoi_g_retriever.jsonl", names)
            self.assertIn("pyg_nodes.csv", names)
            self.assertIn("pyg_edges.csv", names)

        loaded_from_zip = load_project_from_export_bytes(zip_bytes, "hanoi_export.zip")
        self.assertEqual(len(loaded_from_zip["edges"]), len(self.project["edges"]))

        res_zip = retrieve_subgraph(
            loaded_from_zip,
            "Chùa Một Cột được xây dựng dưới triều vua nào?",
            method="pcst",
            max_edges=6,
        )
        self.assertTrue(any(n["id"] == "n_ly_thai_tong" for n in res_zip["subgraph_nodes"]))

        json_bytes = approved_json_bytes(self.project)
        loaded_from_json = load_project_from_export_bytes(json_bytes, "do_thi_da_duyet.json")
        self.assertEqual(len(loaded_from_json["edges"]), len(self.project["edges"]))

    def test_benchmark_generation_and_evaluation(self) -> None:
        benchmarks = generate_qa_benchmark(self.project, num_questions=6)
        self.assertGreaterEqual(len(benchmarks), 2)
        eval_out = evaluate_retrieval_methods(self.project, benchmarks, max_edges=8)
        summary = eval_out["summary_table"]
        self.assertEqual(len(summary), 3)
        codes = [row["Mã"] for row in summary]
        self.assertEqual(codes, ["naive_topk", "ppr", "pcst"])
        pcst_row = summary[2]
        self.assertEqual(pcst_row["Thu hồi Đáp án Đích (%)"], 100.0)

    def test_answer_question_with_graph_llm_and_extractive_fallback(self) -> None:
        dummy_llm = _DummyLLMClient("Chùa Một Cột được xây dựng dưới triều vua Lý Thái Tông [E1] thuộc Triều đại nhà Lý [E2].")
        out_llm = answer_question_with_graph(
            self.project,
            "Chùa Một Cột được xây dựng dưới triều vua nào?",
            method="pcst",
            llm_client=dummy_llm,
        )
        self.assertTrue(out_llm["used_llm"])
        self.assertIn("[E1]", out_llm["answer"])
        self.assertEqual(len(dummy_llm.calls), 1)

        # Fallback extractive khi không truyền API key và không truyền llm_client
        out_ext = answer_question_with_graph(
            self.project,
            "Chùa Một Cột được xây dựng dưới triều vua nào?",
            method="pcst",
            api_key="",
        )
        self.assertFalse(out_ext["used_llm"])
        self.assertIn("Chùa Một Cột", out_ext["answer"])

    def test_facade_and_frontend_client_exposure(self) -> None:
        facade = get_facade()
        client = FrontendClient(facade)
        sub = client.retrieve_subgraph(self.project, "Chùa Một Cột khởi dựng vào năm nào?", method="pcst", max_edges=5)
        self.assertIn("subgraph_edges", sub)
        bench = client.generate_qa_benchmark(self.project, num_questions=3)
        self.assertGreaterEqual(len(bench), 1)

    def test_natural_language_qa_generator_quality(self) -> None:
        from backend.domain.graph.qa_generator import (
            classify_relation_semantic,
            generate_training_qa_dataset,
            synthesize_1hop_natural_question,
            synthesize_2hop_bridge_question,
        )

        self.assertEqual(classify_relation_semantic("tọa lạc tại"), "LOCATION")
        self.assertEqual(classify_relation_semantic("được xây dựng dưới triều vua"), "AGENT_CREATOR")
        self.assertEqual(classify_relation_semantic("thuộc vương triều"), "DYNASTY_ORG")
        self.assertEqual(classify_relation_semantic("khởi dựng vào"), "TEMPORAL")

        q_1hop = synthesize_1hop_natural_question("Chùa Một Cột", "tọa lạc tại", "Hà Nội", "Địa danh")
        self.assertIn("Chùa Một Cột", q_1hop)
        self.assertNotIn("có mối quan hệ", q_1hop)
        self.assertNotIn("theo đồ thị tri thức", q_1hop)
        self.assertNotIn("đối tượng hay thông tin nào", q_1hop)

        q_2hop = synthesize_2hop_bridge_question(
            "Chùa Một Cột",
            "được xây dựng dưới triều vua",
            "Lý Thái Tông",
            "Nhân vật",
            "thuộc vương triều",
            "Triều đại nhà Lý",
            "Tổ chức",
        )
        self.assertIn("Chùa Một Cột", q_2hop)
        self.assertTrue("triều đại" in q_2hop or "vương triều" in q_2hop or "vua" in q_2hop)
        self.assertNotIn("có mối quan hệ", q_2hop)
        self.assertNotIn("đối tượng hay thông tin nào", q_2hop)

        ds = generate_training_qa_dataset(self.project, max_samples=20)
        self.assertGreaterEqual(ds["total_samples"], 2)
        self.assertIn("train_samples", ds)
        self.assertIn("val_samples", ds)
        self.assertIn("test_samples", ds)
        sample = ds["all_samples"][0]
        self.assertIn("seed_pyg_ids", sample)
        self.assertIn("gold_pyg_node_ids", sample)
        self.assertIn("gold_pyg_edge_ids", sample)
        self.assertIn("textualized_subgraph", sample)


if __name__ == "__main__":
    unittest.main()
