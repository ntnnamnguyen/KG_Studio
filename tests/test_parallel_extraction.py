"""Unit tests cho tính năng trích xuất tri thức đa luồng đồng thời (Parallel Concurrent Extraction)."""
import unittest
from unittest.mock import MagicMock, patch

from backend.domain.extraction.base_engine import EngineOutput
from backend.facade import KGStudioFacade


class TestParallelExtraction(unittest.TestCase):
    def setUp(self):
        self.facade = KGStudioFacade()
        self.sample_project = {
            "name": "TestParallelProj",
            "project_id": "test_parallel_p1",
            "extraction_mode": "closed",
            "relations": ["tọa lạc tại", "thờ phụng"],
            "nodes": [],
            "edges": [],
            "runs": [],
            "documents": [
                {
                    "id": "doc1",
                    "name": "hanoi_history.txt",
                    "text": "Chùa Một Cột tọa lạc tại Hà Nội. Đền Quán Thánh thờ phụng Huyền Thiên Trấn Vũ.",
                }
            ],
        }

    def test_extract_chunks_parallel_sequential(self):
        """Kiểm tra chế độ 1 luồng (sequential) chạy mượt mà."""
        doc = self.sample_project["documents"][0]
        chunks = [
            {"chunk_number": 1, "text": "Chùa Một Cột tọa lạc tại Hà Nội."},
            {"chunk_number": 2, "text": "Đền Quán Thánh thờ phụng Huyền Thiên Trấn Vũ."},
        ]
        tasks = [(doc, chunks[0]), (doc, chunks[1])]

        mock_output = EngineOutput(
            payload={"thuc_the": [], "quan_he": []},
            ingest_stats={"added_nodes": 2, "added_edges": 1},
            input_tokens=100,
            output_tokens=50,
        )

        progress_calls = []

        def on_prog(done_idx, total_cnt, d, r, out, err):
            progress_calls.append((done_idx, total_cnt, r["chunk_number"]))

        with patch.object(self.facade, "extract_chunk", return_value=mock_output) as mock_chunk:
            with patch.object(self.facade, "save_project") as mock_save:
                res = self.facade.extract_chunks_parallel(
                    self.sample_project,
                    tasks,
                    provider="DeepSeek",
                    api_key="sk-test",
                    model="deepseek-chat",
                    max_workers=1,
                    on_progress=on_prog,
                    save_after_chunk=True,
                )

        self.assertEqual(res["total"], 2)
        self.assertEqual(res["success_count"], 2)
        self.assertEqual(res["failed_count"], 0)
        self.assertEqual(len(progress_calls), 2)
        self.assertEqual(mock_chunk.call_count, 2)
        self.assertEqual(mock_save.call_count, 2)

    def test_extract_chunks_parallel_multi_threaded(self):
        """Kiểm tra chế độ đa luồng đồng thời (max_workers=3)."""
        doc = self.sample_project["documents"][0]
        chunks = [
            {"chunk_number": i, "text": f"Nội dung đoạn số {i}"}
            for i in range(1, 7)
        ]
        tasks = [(doc, c) for c in chunks]

        mock_output = EngineOutput(
            payload={"thuc_the": [], "quan_he": []},
            ingest_stats={"added_nodes": 1, "added_edges": 1},
            input_tokens=80,
            output_tokens=30,
        )

        progress_records = []

        def on_prog(done_idx, total_cnt, d, r, out, err):
            progress_records.append((done_idx, total_cnt, r["chunk_number"], err is None))

        with patch.object(self.facade, "extract_chunk", return_value=mock_output) as mock_chunk:
            with patch.object(self.facade, "save_project") as mock_save:
                res = self.facade.extract_chunks_parallel(
                    self.sample_project,
                    tasks,
                    provider="DeepSeek",
                    api_key="sk-test",
                    model="deepseek-chat",
                    max_workers=3,
                    on_progress=on_prog,
                    save_after_chunk=True,
                )

        self.assertEqual(res["total"], 6)
        self.assertEqual(res["success_count"], 6)
        self.assertEqual(res["failed_count"], 0)
        self.assertEqual(len(progress_records), 6)
        self.assertEqual(mock_chunk.call_count, 6)
        self.assertEqual(mock_save.call_count, 6)

    def test_extract_chunks_parallel_with_errors(self):
        """Kiểm tra đa luồng khi có 1 đoạn bị lỗi thì không làm sập toàn bộ tiến trình."""
        doc = self.sample_project["documents"][0]
        chunks = [
            {"chunk_number": 1, "text": "Đoạn 1"},
            {"chunk_number": 2, "text": "Đoạn 2 (Lỗi)"},
            {"chunk_number": 3, "text": "Đoạn 3"},
        ]
        tasks = [(doc, c) for c in chunks]

        def side_effect(project, doc, rec, **kwargs):
            if rec["chunk_number"] == 2:
                raise RuntimeError("API Rate limit exceeded 429")
            return EngineOutput(
                payload={"thuc_the": [], "quan_he": []},
                ingest_stats={"added_nodes": 1, "added_edges": 1},
            )

        with patch.object(self.facade, "extract_chunk", side_effect=side_effect):
            with patch.object(self.facade, "save_project"):
                res = self.facade.extract_chunks_parallel(
                    self.sample_project,
                    tasks,
                    provider="DeepSeek",
                    api_key="sk-test",
                    model="deepseek-chat",
                    max_workers=2,
                    save_after_chunk=True,
                )

        self.assertEqual(res["total"], 3)
        self.assertEqual(res["success_count"], 2)
        self.assertEqual(res["failed_count"], 1)
        self.assertEqual(len(res["failed_tasks"]), 1)
        self.assertEqual(res["failed_tasks"][0]["rec"]["chunk_number"], 2)
        self.assertIn("Rate limit", res["failed_tasks"][0]["error"])

    @patch("backend.domain.extraction.engines.fixed_catalog.LLMGateway.extract")
    def test_real_engine_parallel_with_thread_locks(self, mock_llm_extract):
        """Kiểm tra đa luồng thực thi xuyên suốt engine thật và bảo vệ lock không bị race condition."""
        mock_result = MagicMock()
        mock_result.data = {
            "thuc_the": [{"ten": "Chùa Một Cột", "loai": "di tích", "mo_ta": "Ngôi chùa cổ"}],
            "quan_he": [
                {
                    "nguon": "Chùa Một Cột",
                    "quan_he": "tọa lạc tại",
                    "dich": "Hà Nội",
                    "trich_dan": "Chùa Một Cột tọa lạc tại Hà Nội",
                }
            ],
        }
        mock_result.input_tokens = 50
        mock_result.output_tokens = 25
        mock_result.raw = '{"thuc_the": [], "quan_he": []}'
        mock_result.prepared_request = None
        mock_llm_extract.return_value = mock_result

        doc = self.sample_project["documents"][0]
        chunks = [
            {"chunk_number": i, "text": f"Đoạn {i}: Chùa Một Cột tọa lạc tại Hà Nội"}
            for i in range(1, 6)
        ]
        tasks = [(doc, c) for c in chunks]

        with patch.object(self.facade, "save_project"):
            res = self.facade.extract_chunks_parallel(
                self.sample_project,
                tasks,
                provider="DeepSeek",
                api_key="sk-test",
                model="deepseek-chat",
                max_workers=3,
                save_after_chunk=True,
            )

        self.assertEqual(res["success_count"], 5)
        # Các node và edge được bảo vệ lock và sáp nhập an toàn
        node_names = [n["name"] for n in self.sample_project["nodes"]]
        self.assertIn("Chùa Một Cột", node_names)
        self.assertEqual(len(self.sample_project["runs"]), 5)



if __name__ == "__main__":
    unittest.main()
