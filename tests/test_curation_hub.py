"""Unit tests cho Trung tâm Kiểm duyệt & Chuẩn hóa Tri thức Hợp nhất (Knowledge Curation Hub)."""
from __future__ import annotations

import unittest

from frontend.state.session import PAGE_LABELS
from frontend.components.shared_curation_ui import compute_filter_hash, paginate_items
from frontend.pages.p04_curation_hub import (
    compute_curation_overview_counts,
    compute_edc_overview_counts,
    render_curation_hub_page,
)


class TestKnowledgeCurationHub(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {
            "name": "Test_Project",
            "documents": [{"id": "d1", "name": "doc1.txt", "text": "Hà Nội là thủ đô."}],
            "schema_proposals": [
                {"id": "p_type", "kind": "entity_types", "name": "thành phố", "status": "pending"},
                {"id": "p_rel", "kind": "relations", "name": "là thủ đô của", "status": "approved"},
            ],
            "nodes": [
                {"id": "n1", "name": "Hà Nội", "kind": "thành phố"},
                {"id": "n2", "name": "Việt Nam", "kind": "quốc gia"},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "relation": "là thủ đô của", "status": "pending"},
            ],
            "runs": [],
        }

    def test_shared_pagination(self) -> None:
        items = list(range(100))
        page_items, cur_page, total_pages = paginate_items(items, page=2, page_size=20)
        self.assertEqual(len(page_items), 20)
        self.assertEqual(cur_page, 2)
        self.assertEqual(total_pages, 5)
        self.assertEqual(page_items[0], 20)
        self.assertEqual(page_items[-1], 39)

    def test_shared_filter_hash(self) -> None:
        h1 = compute_filter_hash({"status": "pending", "search": "Hà Nội"})
        h2 = compute_filter_hash({"search": "hà nội", "status": "pending"})
        self.assertEqual(h1, h2)

    def test_edc_overview_counts(self) -> None:
        counts = compute_edc_overview_counts(self.project)
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["approved"], 1)
        self.assertIn("entity_types", counts["by_kind"])
        self.assertIn("relations", counts["by_kind"])

    def test_hub_render_all_tabs(self) -> None:
        for tab in ("schema", "edges", "entities"):
            try:
                render_curation_hub_page(self.project, default_tab=tab)
            except Exception as exc:
                self.fail(f"render_curation_hub_page failed on tab '{tab}': {exc}")

    def test_renumbered_page_labels(self) -> None:
        from frontend.state.session import normalize_page_label
        self.assertEqual(len(PAGE_LABELS), 5)
        self.assertEqual(PAGE_LABELS[0], "1. Tài liệu")
        self.assertEqual(PAGE_LABELS[1], "2. Thiết lập")
        self.assertEqual(PAGE_LABELS[2], "3. Trích xuất")
        self.assertEqual(PAGE_LABELS[3], "4. Rà soát")
        self.assertEqual(PAGE_LABELS[4], "5. Khai thác")

        # Kiểm tra tính tương thích ngược của nhãn cũ qua normalize_page_label
        self.assertEqual(normalize_page_label("1. Dự án & Tài liệu"), "1. Tài liệu")
        self.assertEqual(normalize_page_label("2. Danh mục, EDC+R & ML Lab"), "2. Thiết lập")
        self.assertEqual(normalize_page_label("3. Trích xuất & Trace"), "3. Trích xuất")
        self.assertEqual(normalize_page_label("4. Kiểm duyệt & Chuẩn hóa Tri thức"), "4. Rà soát")
        self.assertEqual(normalize_page_label("5. Đồ thị & Xuất Neo4j"), "5. Khai thác")

    def test_granular_inspect_edge_schema_status(self) -> None:
        from backend.domain.curation.validation import inspect_edge_schema_status

        project = {
            "name": "Granular_Test",
            "relations": ["là thủ đô của"],
            "relation_notes": {"là thủ đô của": {"description": "", "definition": "thủ đô"}},
            "entity_types": [{"name": "thành phố"}, {"name": "quốc gia"}],
            "schema_proposals": [
                {"id": "p_rel_rej", "kind": "relations", "name": "tọa_lạc_tại", "status": "rejected"},
                {"id": "p_type_pend", "kind": "entity_types", "name": "vùng đất", "status": "pending"},
            ],
            "nodes": [
                {"id": "n1", "name": "Hà Nội", "kind": "thành phố", "schema_proposal_ids": []},
                {"id": "n2", "name": "Việt Nam", "kind": "quốc gia", "schema_proposal_ids": []},
                {"id": "n3", "name": "Ba Vì", "kind": "vùng đất", "schema_proposal_ids": ["p_type_pend"]},
            ],
            "edges": [
                # Edge 1: Cả 3 thành phần R, S, T đều đã trong catalog -> Valid 100%
                {"id": "e1", "source": "n1", "target": "n2", "relation": "là thủ đô của", "status": "pending"},
                # Edge 2: Quan hệ bị từ chối
                {"id": "e2", "source": "n1", "target": "n2", "relation": "tọa_lạc_tại", "schema_proposal_ids": ["p_rel_rej"]},
                # Edge 3: Loại nguồn Ba Vì (vùng đất) đang chờ duyệt
                {"id": "e3", "source": "n3", "target": "n1", "relation": "là thủ đô của", "schema_proposal_ids": []},
            ],
        }

        # Edge 1 phải Hợp lệ 100%
        st1 = inspect_edge_schema_status(project, project["edges"][0])
        self.assertEqual(st1["status_code"], "valid")
        self.assertEqual(st1["label"], "Hợp lệ")
        self.assertEqual(st1["badge_label"], "✅ Hợp lệ")
        self.assertEqual(len(st1["blocking_proposal_ids"]), 0)

        # Edge 2 bị chặn do quan hệ bị từ chối
        st2 = inspect_edge_schema_status(project, project["edges"][1])
        self.assertEqual(st2["status_code"], "rejected_proposal")
        self.assertIn("tọa_lạc_tại", st2["issue"])
        self.assertIn("p_rel_rej", st2["blocking_proposal_ids"])

        # Edge 3 quan hệ 'là thủ đô của' hợp lệ, nhưng loại nguồn 'vùng đất' đang chờ duyệt
        st3 = inspect_edge_schema_status(project, project["edges"][2])
        self.assertEqual(st3["status_code"], "pending_proposal")
        self.assertEqual(st3["badge_label"], "⛔ Loại nguồn chờ duyệt")
        self.assertIn("vùng đất", st3["issue"])
        self.assertIn("p_type_pend", st3["blocking_proposal_ids"])

    def test_pure_relation_display_in_table(self) -> None:
        from frontend.components.curation_table import build_edge_table_rows

        project = {
            "name": "Display_Test",
            "relations": ["là thủ đô của"],
            "relation_notes": {"là thủ đô của": {"description": "", "definition": "thủ đô"}},
            "entity_types": [{"name": "thành phố"}, {"name": "quốc gia"}],
            "schema_proposals": [],
            "nodes": [
                {"id": "n1", "name": "Hà Nội", "kind": "thành phố"},
                {"id": "n2", "name": "Việt Nam", "kind": "quốc gia"},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "relation": "là thủ đô của", "status": "pending"},
            ],
        }
        rows = build_edge_table_rows(project, project["edges"], selected_ids=[])
        self.assertEqual(len(rows), 1)
        # Tên quan hệ hiển thị thuần túy, không có suffix nhãn cạnh
        self.assertEqual(rows[0]["relation_display"], "là thủ đô của")
        self.assertEqual(rows[0]["schema_badge"], "✅ Hợp lệ")

    def test_quick_apply_edge_batch(self) -> None:
        from frontend.components.curation_table import quick_apply_edge_batch
        from frontend.client import FrontendClient
        from shared.constants import STATUS_APPROVED, STATUS_PENDING

        project = {
            "project_id": "p_quick_test",
            "name": "Quick_Edge_Test",
            "documents": [{"id": "d1", "name": "doc.txt", "text": "Hà Nội là thủ đô của Việt Nam. Huế là cố đô."}],
            "relations": ["là thủ đô của", "là cố đô của"],
            "relation_notes": {
                "là thủ đô của": {"definition": "thủ đô", "description": ""},
                "là cố đô của": {"definition": "cố đô", "description": ""},
            },
            "entity_types": [{"name": "thành phố"}, {"name": "quốc gia"}],
            "nodes": [
                {"id": "n1", "name": "Hà Nội", "kind": "thành phố"},
                {"id": "n2", "name": "Việt Nam", "kind": "quốc gia"},
                {"id": "n3", "name": "Huế", "kind": "thành phố"},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "relation": "là thủ đô của", "status": STATUS_PENDING, "evidence": "Hà Nội là thủ đô của Việt Nam", "doc_id": "d1"},
                {"id": "e2", "source": "n3", "target": "n2", "relation": "là cố đô của", "status": STATUS_PENDING, "evidence": "Huế là cố đô", "doc_id": "d1"},
            ],
            "schema_proposals": [],
        }
        state: dict = {}
        client = FrontendClient()
        # Duyệt nhanh cả 2 cạnh đã chọn trong 1 thao tác duy nhất
        res = quick_apply_edge_batch(project, ["e1", "e2"], "approve", client=client, state_store=state)
        self.assertEqual(res.applied_count, 2)
        self.assertEqual(res.skipped_count, 0)
        self.assertEqual(project["edges"][0]["status"], STATUS_APPROVED)
        self.assertEqual(project["edges"][1]["status"], STATUS_APPROVED)

    def test_entity_selection_and_reconciliation(self) -> None:
        from frontend.state.session import (
            clear_entity_selection,
            get_curation_section_state,
            reconcile_entity_selection_with_filter,
            select_all_filtered_entities,
            select_page_entities,
            toggle_entity_selection,
        )

        project = {
            "project_id": "p_ent_test",
            "name": "Ent_Selection_Test",
            "nodes": [{"id": f"node_{i}", "name": f"Node {i}", "kind": "thành phố"} for i in range(10)],
            "edges": [],
            "documents": [],
        }
        state: dict = {}
        # 1. Chọn 1 entity
        toggle_entity_selection(project, "node_1", True, state)
        e_state = get_curation_section_state(project, "entities", state)
        self.assertIn("node_1", e_state["selected_ids"])

        # 2. Chọn trang
        select_page_entities(project, project["nodes"][:5], state)
        self.assertEqual(len(e_state["selected_ids"]), 5)

        # 3. Chọn tất cả
        select_all_filtered_entities(project, project["nodes"], state)
        self.assertEqual(len(e_state["selected_ids"]), 10)

        # 4. Bỏ chọn
        clear_entity_selection(project, state)
        self.assertEqual(len(e_state["selected_ids"]), 0)

        # 5. Reconcile với bộ lọc
        toggle_entity_selection(project, "node_1", True, state)
        toggle_entity_selection(project, "node_9", True, state)
        # Bộ lọc mới chỉ chứa node_0..node_4 -> node_9 bị loại bỏ tự động
        reconcile_entity_selection_with_filter(project, "sig_new", project["nodes"][:5], state)
        self.assertEqual(e_state["selected_ids"], ["node_1"])

    def test_quick_apply_proposal_batch(self) -> None:
        from frontend.components.edc_bulk_actions import quick_apply_proposal_batch
        from frontend.client import FrontendClient

        project = {
            "project_id": "p_prop_test",
            "name": "Prop_Test",
            "documents": [],
            "relations": [],
            "entity_types": [],
            "nodes": [],
            "edges": [],
            "schema_proposals": [
                {"id": "p1", "kind": "entity_types", "name": "di tích", "definition": "Công trình di tích", "status": "pending"},
                {"id": "p2", "kind": "entity_types", "name": "lễ hội", "definition": "Lễ hội văn hóa", "status": "pending"},
            ],
        }
        state: dict = {}
        client = FrontendClient()
        res = quick_apply_proposal_batch(project, "entity_types", ["p1", "p2"], "approve", client=client, state_store=state)
        self.assertEqual(res.applied_count, 2)
        # Cả 2 đề xuất chuyển sang approved và được nạp vào entity_types catalog
        self.assertEqual(project["schema_proposals"][0]["status"], "approved")
        self.assertEqual(project["schema_proposals"][1]["status"], "approved")
        type_names = [t["name"] for t in project["entity_types"]]
        self.assertIn("di tích", type_names)
        self.assertIn("lễ hội", type_names)


    def test_quick_apply_edge_batch_with_schema_bypass(self) -> None:
        """Kiểm tra duyệt lô các cạnh có đề xuất bị từ chối/ngoài danh mục khi bật allow_schema_bypass."""
        from frontend.components.curation_table import quick_apply_edge_batch
        from frontend.client import FrontendClient
        from backend.domain.curation.validation import inspect_edge_schema_status, is_edge_exportable
        from shared.constants import STATUS_APPROVED, STATUS_PENDING

        project = {
            "project_id": "p_bypass_test",
            "name": "Bypass_Test",
            "documents": [{"id": "d1", "name": "doc.txt", "text": "Đền thờ Quang Trung có diện tích 300 m2."}],
            "relations": [],
            "relation_types": [],
            "entity_types": [{"name": "công trình"}],
            "nodes": [
                {"id": "n1", "name": "Đền thờ Quang Trung", "kind": "công trình"},
                {"id": "n2", "name": "300 m2", "kind": "số đo"},
            ],
            "edges": [
                {
                    "id": "e_bypass",
                    "source": "n1",
                    "target": "n2",
                    "relation": "có_diện_tích",
                    "status": STATUS_PENDING,
                    "evidence": "có diện tích 300 m2",
                    "doc_id": "d1",
                    "schema_proposal_ids": ["p_rel_rej"],
                }
            ],
            "schema_proposals": [
                {"id": "p_rel_rej", "kind": "relations", "name": "có_diện_tích", "status": "rejected"},
                {"id": "p_kind_so_do", "kind": "entity_types", "name": "số đo", "status": "pending"},
            ],
        }

        # Ban đầu cạnh bị gắn nhãn ❌ Đề xuất bị từ chối
        st_before = inspect_edge_schema_status(project, project["edges"][0])
        self.assertEqual(st_before["status_code"], "rejected_proposal")
        self.assertEqual(st_before["badge_label"], "❌ Đề xuất bị từ chối")

        # Duyệt nhanh với allow_schema_bypass=True
        state: dict = {}
        client = FrontendClient()
        res = quick_apply_edge_batch(
            project,
            ["e_bypass"],
            "approve",
            allow_schema_bypass=True,
            auto_sync_catalog=True,
            client=client,
            state_store=state,
        )

        self.assertEqual(res.applied_count, 1)
        self.assertEqual(res.skipped_count, 0)
        self.assertEqual(project["edges"][0]["status"], STATUS_APPROVED)

        # Kiểm tra tự động phục hồi và nạp vào danh mục:
        # 1. Đề xuất quan hệ và loại thực thể được mở khóa sang approved
        p_rel = next(p for p in project["schema_proposals"] if p["id"] == "p_rel_rej")
        self.assertEqual(p_rel["status"], "approved")
        p_kind = next(p for p in project["schema_proposals"] if p["id"] == "p_kind_so_do")
        self.assertEqual(p_kind["status"], "approved")

        # 2. Quan hệ có_diện_tích và loại số đo được nạp vào catalog
        rel_names = [r["name"] for r in project["relation_types"]]
        self.assertIn("có_diện_tích", rel_names)
        type_names = [t["name"] for t in project["entity_types"]]
        self.assertIn("số đo", type_names)

        # 3. Tình trạng Lược đồ của cạnh chuyển ngay thành ✅ Hợp lệ
        st_after = inspect_edge_schema_status(project, project["edges"][0])
        self.assertEqual(st_after["status_code"], "valid")
        self.assertEqual(st_after["badge_label"], "✅ Hợp lệ")

        # 4. Cạnh đạt chuẩn đủ điều kiện xuất đồ thị (Trang 5 Khai thác / Neo4j)
        self.assertTrue(is_edge_exportable(project, project["edges"][0]))


if __name__ == "__main__":
    unittest.main()

