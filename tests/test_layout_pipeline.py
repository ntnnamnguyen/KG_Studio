"""Bộ kiểm thử đơn vị cho Luồng Quy trình 5 bước và Giao diện Hợp nhất (Layout & Pipeline Engine).

Kiểm thử toàn diện:
1. Danh sách bước PIPELINE_STEPS & PAGE_LABELS.
2. Hàm chuẩn hóa nhãn tương thích ngược normalize_page_label.
3. Cơ chế điều hướng navigate_to_step & get_active_step.
4. Engine tính độ sẵn sàng quy trình compute_pipeline_readiness.
5. Render component Header Banner & Next Action.
6. Khả năng nạp và render thành công của cả 5 bước nghiệp vụ.
"""
from __future__ import annotations

import unittest
import streamlit as st

from frontend.components.pipeline_banner import (
    render_pipeline_header,
    render_step_next_action,
)
from frontend.pages.p01_projects_docs import render_projects_docs_page
from frontend.pages.p02_catalogs_prompts import render_catalogs_prompts_page
from frontend.pages.p03_extraction import render_extraction_page
from frontend.pages.p04_curation_hub import render_curation_hub_page
from frontend.pages.p05_graph_export import render_graph_export_page
from frontend.state.session import (
    LEGACY_PAGE_LABEL_MAP,
    PAGE_LABELS,
    PIPELINE_STEPS,
    compute_pipeline_readiness,
    get_active_step,
    navigate_to_step,
    normalize_page_label,
)


class TestLayoutPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_project = {
            "project_id": "test_pipe_001",
            "name": "Pipeline Test Project",
            "extraction_mode": "closed",
            "entity_types": ["Nhân vật", "Địa danh"],
            "relations": ["sinh_tai", "dong_do"],
            "documents": [
                {
                    "id": "doc_1",
                    "name": "lich_su.txt",
                    "text": "Lý Công Uẩn sinh năm 974, dời đô về Thăng Long năm 1010.",
                    "place_scope": "Hà Nội",
                }
            ],
            "runs": [
                {
                    "doc_id": "doc_1",
                    "doc_name": "lich_su.txt",
                    "chunk_number": 1,
                    "status": "ok",
                }
            ],
            "nodes": [
                {"id": "node_ly_cong_uan", "name": "Lý Công Uẩn", "type": "Nhân vật"},
                {"id": "node_thang_long", "name": "Thăng Long", "type": "Địa danh"},
            ],
            "edges": [
                {
                    "id": "edge_1",
                    "source": "node_ly_cong_uan",
                    "relation": "dong_do",
                    "target": "node_thang_long",
                    "status": "Đã duyệt",
                    "evidence": "dời đô về Thăng Long",
                    "doc_name": "lich_su.txt",
                },
                {
                    "id": "edge_2",
                    "source": "node_ly_cong_uan",
                    "relation": "sinh_tai",
                    "target": "node_thang_long",
                    "status": "Chờ duyệt",
                    "evidence": "sinh năm 974",
                    "doc_name": "lich_su.txt",
                },
            ],
            "schema_proposals": [],
        }

    def test_pipeline_steps_and_labels_consistency(self) -> None:
        self.assertEqual(len(PIPELINE_STEPS), 5)
        self.assertEqual(len(PAGE_LABELS), 5)
        self.assertEqual(PIPELINE_STEPS, ["documents", "setup", "extraction", "review", "explore"])
        self.assertEqual(
            PAGE_LABELS,
            ["1. Tài liệu", "2. Thiết lập", "3. Trích xuất", "4. Rà soát", "5. Khai thác"],
        )

    def test_legacy_label_normalization(self) -> None:
        for legacy, modern in LEGACY_PAGE_LABEL_MAP.items():
            self.assertEqual(normalize_page_label(legacy), modern)

        # Kiểm tra nhãn chuẩn hóa không đổi
        for label in PAGE_LABELS:
            self.assertEqual(normalize_page_label(label), label)

        # Fallback nhãn không xác định
        self.assertEqual(normalize_page_label("unknown_label_xyz"), PAGE_LABELS[0])

    def test_navigation_and_active_step(self) -> None:
        # Điều hướng theo index
        navigate_to_step(2)
        step_id, idx, label = get_active_step()
        self.assertEqual(step_id, "extraction")
        self.assertEqual(idx, 2)
        self.assertEqual(label, "3. Trích xuất")

        # Điều hướng theo step_id
        navigate_to_step("review")
        step_id, idx, label = get_active_step()
        self.assertEqual(step_id, "review")
        self.assertEqual(idx, 3)
        self.assertEqual(label, "4. Rà soát")

        navigate_to_step("explore")
        step_id, idx, label = get_active_step()
        self.assertEqual(step_id, "explore")
        self.assertEqual(idx, 4)
        self.assertEqual(label, "5. Khai thác")

    def test_pipeline_readiness_computation(self) -> None:
        readiness = compute_pipeline_readiness(self.sample_project)

        # Bước 1: Tài liệu đã có 1 file
        self.assertTrue(readiness["documents"]["ready"])
        self.assertEqual(readiness["documents"]["count"], 1)
        self.assertEqual(readiness["documents"]["badge"], "✓")

        # Bước 2: Thiết lập (đã có danh mục thực thể & quan hệ)
        self.assertTrue(readiness["setup"]["ready"])
        self.assertEqual(readiness["setup"]["badge"], "✓")

        # Bước 3: Đã có 1 lượt trích xuất
        self.assertEqual(readiness["extraction"]["runs_count"], 1)
        self.assertEqual(readiness["extraction"]["errors_count"], 0)
        self.assertEqual(readiness["extraction"]["badge"], "✓")

        # Bước 4: Rà soát (có 1 cạnh chờ duyệt -> badge '●')
        self.assertEqual(readiness["review"]["needs_review_count"], 1)
        self.assertEqual(readiness["review"]["badge"], "●")

        # Bước 5: Khai thác (có 1 cạnh đã duyệt -> ready True)
        self.assertTrue(readiness["explore"]["ready"])
        self.assertEqual(readiness["explore"]["approved_count"], 1)

        # Overall next action nên chỉ đến bước review vì còn 1 cạnh chờ duyệt
        self.assertIn("review", readiness["overall_next"]["step_id"])

    def test_empty_project_readiness(self) -> None:
        empty_project = {
            "name": "Empty Project",
            "documents": [],
            "entity_types": [],
            "relations": [],
            "edges": [],
            "runs": [],
        }
        readiness = compute_pipeline_readiness(empty_project)
        self.assertFalse(readiness["documents"]["ready"])
        self.assertEqual(readiness["documents"]["badge"], "○")
        self.assertEqual(readiness["overall_next"]["step_id"], "documents")

    def test_pipeline_banner_rendering(self) -> None:
        try:
            render_pipeline_header(self.sample_project)
            for step in PIPELINE_STEPS:
                render_step_next_action(step, self.sample_project)
        except Exception as exc:
            self.fail(f"Pipeline banner rendering failed: {exc}")

    def test_render_all_five_pages(self) -> None:
        # Đảm bảo cả 5 màn hình render trơn tru không phát sinh ngoại lệ
        try:
            render_projects_docs_page(self.sample_project)
        except Exception as exc:
            self.fail(f"render_projects_docs_page failed: {exc}")

        try:
            render_catalogs_prompts_page(self.sample_project)
        except Exception as exc:
            self.fail(f"render_catalogs_prompts_page failed: {exc}")

        try:
            render_extraction_page(self.sample_project)
        except Exception as exc:
            self.fail(f"render_extraction_page failed: {exc}")

        try:
            render_curation_hub_page(self.sample_project)
        except Exception as exc:
            self.fail(f"render_curation_hub_page failed: {exc}")

        try:
            render_graph_export_page(self.sample_project)
        except Exception as exc:
            self.fail(f"render_graph_export_page failed: {exc}")

    def test_graph_export_page_slider_with_many_edges(self) -> None:
        proj = dict(self.sample_project)
        proj["project_id"] = "test_pipe_many_edges"
        proj["entity_types"] = [
            {"name": "Nhân vật", "description": "Con người", "definition": "Con người"},
            {"name": "Địa danh", "description": "Nơi chốn", "definition": "Nơi chốn"},
        ]
        proj["nodes"] = [
            {"id": "node_ly_cong_uan", "name": "Lý Công Uẩn", "kind": "Nhân vật"},
            {"id": "node_thang_long", "name": "Thăng Long", "kind": "Địa danh"},
        ]
        proj["edges"] = [
            {
                "id": f"edge_{i}",
                "source": "node_ly_cong_uan",
                "relation": "dong_do",
                "target": "node_thang_long",
                "status": "Đã duyệt",
                "evidence": "dời đô về Thăng Long",
                "doc_id": "doc_1",
                "doc_name": "lich_su.txt",
            }
            for i in range(120)
        ]
        limit_state_key = "_p06_edge_limit_test_pipe_many_edges"
        st.session_state.pop(limit_state_key, None)
        render_graph_export_page(proj)
        self.assertEqual(st.session_state.get(limit_state_key), 60)

        # Cho phép kéo lên tối đa tổng số cạnh (120)
        st.session_state[limit_state_key] = 120
        render_graph_export_page(proj)
        self.assertEqual(st.session_state.get(limit_state_key), 120)


if __name__ == "__main__":
    unittest.main()
