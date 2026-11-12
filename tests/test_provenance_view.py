"""Kiểm thử tính năng Truy vết Nguồn gốc & Đoạn trích Văn bản (Provenance & Chunk Context)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from frontend.components.merge.provenance_view import (
    get_chunk_info,
    highlight_text_html,
    render_entity_provenance_panel,
    render_relation_provenance_panel,
)


class ProvenanceViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {
            "name": "test_provenance",
            "documents": [
                {
                    "id": "doc_001",
                    "name": "den_hai_ba_trung.txt",
                    "text": (
                        "Đền Hai Bà Trưng còn gọi là đền Hạ Lôi tọa lạc tại xã Mê Linh, thành phố Hà Nội. "
                        "Đây là di tích lịch sử quốc gia đặc biệt thờ Trưng Trắc và Trưng Nhị."
                    ),
                    "pages": [],
                },
                {
                    "id": "doc_002",
                    "name": "chua_mot_cot.pdf",
                    "text": (
                        "[Trang 1]\nChùa Một Cột có tên chữ là Diên Hựu tự, tọa lạc tại quận Ba Đình, Hà Nội. "
                        "Ngôi chùa được khởi dựng vào năm 1049 dưới thời vua Lý Thái Tông."
                    ),
                    "pages": [{"page": 1, "start": 0}],
                },
            ],
            "nodes": [
                {
                    "id": "node_001",
                    "name": "Đền Hai Bà Trưng",
                    "kind": "di tích",
                    "description": "Đền thờ Hai Bà Trưng tại Mê Linh",
                    "aliases": ["đền Hạ Lôi"],
                    "documents": ["doc_001"],
                    "edc_observations": [
                        {
                            "doc_id": "doc_001",
                            "chunk_number": 1,
                            "name": "Đền Hai Bà Trưng",
                            "kind": "di tích",
                            "description": "Đền Hạ Lôi thờ Hai Bà Trưng",
                        }
                    ],
                },
                {
                    "id": "node_002",
                    "name": "Chùa Một Cột",
                    "kind": "di tích",
                    "description": "Diên Hựu tự",
                    "aliases": ["Diên Hựu tự"],
                    "documents": ["doc_002"],
                    "edc_observations": [
                        {
                            "doc_id": "doc_002",
                            "chunk_number": 1,
                            "name": "Chùa Một Cột",
                            "kind": "di tích",
                            "description": "Chùa Diên Hựu",
                        }
                    ],
                },
            ],
            "edges": [
                {
                    "id": "edge_001",
                    "source": "node_001",
                    "target": "node_002",
                    "relation": "cùng địa bàn",
                    "evidence": "tọa lạc tại xã Mê Linh, thành phố Hà Nội",
                    "doc_id": "doc_001",
                    "doc_name": "den_hai_ba_trung.txt",
                    "chunk_number": 1,
                    "page": None,
                }
            ],
        }

    def test_get_chunk_info_existing_doc(self) -> None:
        info = get_chunk_info(self.project, "doc_001", chunk_number=1)
        self.assertIsNotNone(info)
        self.assertEqual(info["doc_name"], "den_hai_ba_trung.txt")
        self.assertIn("Hạ Lôi", info["text"])
        self.assertEqual(info["chunk_number"], 1)

    def test_get_chunk_info_pdf_pages(self) -> None:
        info = get_chunk_info(self.project, "doc_002", chunk_number=1)
        self.assertIsNotNone(info)
        self.assertEqual(info["doc_name"], "chua_mot_cot.pdf")
        self.assertIn("Diên Hựu", info["text"])
        self.assertEqual(info["page_from"], 1)

    def test_get_chunk_info_missing_doc(self) -> None:
        info = get_chunk_info(self.project, "doc_nonexistent", chunk_number=1)
        self.assertIsNone(info)

    def test_highlight_text_html_safe_escaping_and_marking(self) -> None:
        malicious_text = "Hà Nội <script>alert('xss')</script> & di tích"
        html_out = highlight_text_html(malicious_text, ["Hà Nội", "di tích"])
        # Phải thoát ký tự < và > của script
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)
        # Phải bọc target trong <mark>
        self.assertIn("<mark", html_out)
        self.assertIn("Hà Nội</mark>", html_out)
        self.assertIn("di tích</mark>", html_out)

    def test_highlight_text_html_empty_inputs(self) -> None:
        self.assertIn("Không có nội dung", highlight_text_html("", ["test"]))
        out_no_targets = highlight_text_html("Văn bản thông thường", [])
        self.assertIn("Văn bản thông thường", out_no_targets)
        self.assertNotIn("<mark", out_no_targets)

    @patch("streamlit.tabs")
    @patch("streamlit.columns")
    @patch("streamlit.container")
    @patch("streamlit.markdown")
    @patch("streamlit.caption")
    def test_render_entity_provenance_panel_no_crash(
        self, mock_caption, mock_md, mock_cont, mock_cols, mock_tabs
    ) -> None:
        mock_cols.return_value = (MagicMock(), MagicMock())
        tab_mock = MagicMock()
        mock_tabs.return_value = [tab_mock, tab_mock]
        # Gọi thử với 2 nodes
        render_entity_provenance_panel(self.project, ["node_001", "node_002"])
        self.assertTrue(mock_md.called)

    @patch("streamlit.tabs")
    @patch("streamlit.columns")
    @patch("streamlit.container")
    @patch("streamlit.markdown")
    @patch("streamlit.caption")
    def test_render_relation_provenance_panel_no_crash(
        self, mock_caption, mock_md, mock_cont, mock_cols, mock_tabs
    ) -> None:
        mock_cols.return_value = (MagicMock(), MagicMock())
        tab_mock = MagicMock()
        mock_tabs.return_value = [tab_mock]
        render_relation_provenance_panel(self.project, ["cùng địa bàn"])
        self.assertTrue(mock_md.called)


if __name__ == "__main__":
    unittest.main()
