"""Kiểm thử toàn diện Trang 5: Kiểm duyệt Quan hệ, Quản lý Thực thể & Gộp Thực thể (theo đặc tả curation-merge.md)."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from backend.api.v1 import handle_api_request
from backend.domain.catalogs.service import (
    catalog_rows,
    compute_project_revision,
    decide_proposal,
    propose_term,
)
from backend.domain.curation.service import (
    apply_bulk_entity_merges,
    apply_curation_decisions,
    apply_entity_merge,
    apply_relation_merge,
    bulk_apply_relation_merges,
    collapse_duplicate_edges,
    compute_apparent_duplicate_edge_groups,
    doc_fingerprint,
    duplicate_suggestions,
    evidence_context,
    inspect_edge_schema_status,
    is_edge_exportable,
    mark_pair_not_duplicate,
    mark_relation_pair_not_duplicate,
    preview_curation_decisions,
    preview_entity_merge,
    relation_duplicate_suggestions,
    select_edge_evidence_span,
    set_edge_status,
    update_edge,
    update_node,
)
from backend.domain.dataset_exporter.exporter import ActiveLearningExporter
from backend.domain.documents.processor import add_document
from backend.domain.graph.service import approved_graph, validate_integrity
from backend.facade import KGStudioFacade
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from frontend.client import FrontendClient
from frontend.components.curation_table import (
    build_edge_batch_preview,
    build_edge_table_rows,
    compute_edge_filter_signature,
    execute_edge_batch_apply,
    filter_and_sort_edges,
    filter_and_sort_entities,
    paginate_items,
)
from frontend.components.entity_merge_panel import (
    build_entity_merge_preview,
    execute_entity_merge_apply,
)
from frontend.components.evidence_panel import format_highlighted_evidence_html
from frontend.state.session import (
    PAGE_LABELS,
    clear_edge_selection,
    get_curation_section_state,
     get_edc_table_state,
    navigate_to_edc_proposal_from_curation,
    reconcile_edge_selection_with_filter,
    reset_curation_state_if_project_changed,
    return_to_curation_from_edc,
    select_all_filtered_edges,
    select_page_edges,
    set_focused_edge,
    stage_entities_for_merge,
    toggle_edge_selection,
    update_merge_draft,
)
from shared.catalog_utils import apply_relations, atomic_write
from shared.constants import MODE_EDC_PLUS_R, STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.schemas.curation import (
    CurationReviewRequestDTO,
    EdgeEditRequestDTO,
    EdgeReviewDecisionDTO,
    EntityEditRequestDTO,
    EntityMergeRequestDTO,
)


DOC_TEXT = (
    "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội. "
    "Năm 1049, vua Lý Thái Tông cho xây dựng Chùa Một Cột. "
    "Về sau, Chùa Một Cột tọa lạc tại quận Ba Đình trở thành biểu tượng văn hóa của Thăng Long. "
    "Hoàng thành Thăng Long nằm gần khu vực trung tâm quận Ba Đình."
)


def _seed_curation_project(name: str = "Curation_Merge_Test") -> dict:
    project = empty_project(name)
    project["extraction_mode"] = MODE_EDC_PLUS_R
    apply_relations(
        project,
        [
            {
                "name": "nằm tại",
                "description": "Vị trí địa lý",
                "definition": "Thực thể nguồn nằm tại địa điểm đích.",
            },
            {
                "name": "xây dựng năm",
                "description": "Năm khởi dựng",
                "definition": "Công trình nguồn được xây dựng vào năm đích.",
            },
            {
                "name": "gắn với nhân vật",
                "description": "Nhân vật lịch sử liên quan",
                "definition": "Di tích nguồn gắn liền với nhân vật lịch sử đích.",
            },
        ],
    )
    project["entity_types"] = [
        {
            "name": "di tích",
            "description": "Công trình văn hóa lịch sử",
            "definition": "Công trình kiến trúc, di sản văn hóa lịch sử.",
        },
        {
            "name": "địa điểm",
            "description": "Đơn vị hành chính / địa danh",
            "definition": "Khu vực địa lý hoặc đơn vị hành chính.",
        },
        {
            "name": "nhân vật",
            "description": "Nhân vật lịch sử",
            "definition": "Danh nhân, vua chúa hoặc nhân vật lịch sử.",
        },
        {
            "name": "niên đại",
            "description": "Mốc thời gian",
            "definition": "Năm hoặc giai đoạn lịch sử.",
        },
    ]
    add_document(project, "di_san_ha_noi.txt", DOC_TEXT.encode("utf-8"))
    return project


class CurationMergeTests(unittest.TestCase):
    def test_01_selection_by_id_sort_pagination_filter_pruning_and_project_reset(self) -> None:
        """Kịch bản 1: Chọn một dòng, nhiều dòng, cả trang và tất cả theo bộ lọc; đổi trang, đổi sắp xếp, đổi bộ lọc và đổi dự án."""
        project = _seed_curation_project("Proj_Sel_1")
        doc = project["documents"][0]
        project["nodes"] = [
            {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": [doc["id"]]},
            {"id": "n2", "name": "quận Ba Đình", "kind": "địa điểm", "aliases": [], "documents": [doc["id"]]},
        ]
        project["edges"] = []
        for idx in range(1, 7):
            project["edges"].append(
                {
                    "id": f"e{idx}",
                    "source": "n1",
                    "target": "n2",
                    "relation": "nằm tại" if idx <= 4 else "xây dựng năm",
                    "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                    "evidence_found": True,
                    "doc_id": doc["id"],
                    "doc_name": doc["name"],
                    "doc_fingerprint": doc_fingerprint(doc),
                    "chunk_number": 1,
                    "status": STATUS_PENDING if idx <= 5 else STATUS_APPROVED,
                }
            )

        state: dict = {}
        e_state = get_curation_section_state(project, "edges", state)
        filters = e_state["filters"]
        filters["page_size"] = 2

        filtered = filter_and_sort_edges(project, filters)
        self.assertEqual(len(filtered), 6)

        # Mở xem chi tiết 1 dòng không tự chọn checkbox
        set_focused_edge(project, "e1", state)
        self.assertEqual(e_state["focused_edge_id"], "e1")
        self.assertEqual(e_state["selected_ids"], [])

        # Chọn trang 1 (2 dòng e1, e2)
        page1, _, _ = paginate_items(filtered, 1, 2)
        select_page_edges(project, page1, state)
        self.assertEqual(e_state["selected_ids"], ["e1", "e2"])

        # Đổi sang trang 2 và đổi sắp xếp -> vẫn giữ lựa chọn theo ID
        filters["sort_by"] = "relation"
        filters["sort_desc"] = True
        filtered_sorted = filter_and_sort_edges(project, filters)
        page2, _, _ = paginate_items(filtered_sorted, 2, 2)
        self.assertEqual(e_state["selected_ids"], ["e1", "e2"])

        # Chọn tất cả khớp bộ lọc: chỉ chọn 5 cạnh Chờ duyệt / Cần kiểm tra, loại trừ cạnh e6 Đã duyệt
        select_all_filtered_edges(project, filtered_sorted, state)
        self.assertEqual(set(e_state["selected_ids"]), {"e1", "e2", "e3", "e4", "e5"})

        # Đổi bộ lọc chỉ lấy relation = "nằm tại" (e1..e4) -> tự động bỏ chọn e5 và thông báo rõ
        sig1 = compute_edge_filter_signature(filters)
        reconcile_edge_selection_with_filter(project, sig1, filtered_sorted, state)
        filters["relation"] = "nằm tại"
        filtered_rel = filter_and_sort_edges(project, filters)
        sig2 = compute_edge_filter_signature(filters)
        pruned = reconcile_edge_selection_with_filter(project, sig2, filtered_rel, state)
        self.assertEqual(pruned, 1)
        self.assertEqual(set(e_state["selected_ids"]), {"e1", "e2", "e3", "e4"})
        self.assertIn("Đã bỏ chọn 1 cạnh", e_state["filter_prune_notice"])

        # Đổi dự án -> đặt lại toàn bộ lựa chọn và bộ lọc
        other_project = _seed_curation_project("Proj_Sel_2")
        changed = reset_curation_state_if_project_changed(other_project, state)
        self.assertTrue(changed)
        self.assertEqual(get_curation_section_state(other_project, "edges", state)["selected_ids"], [])

    def test_02_batch_10_edges_with_2_schema_blocked_and_exclude_processed(self) -> None:
        """Kịch bản 2 & 3:
        - Chọn 10 cạnh trong đó có 2 cạnh còn vướng đề xuất EDC chưa duyệt: all_or_nothing bị chặn, valid_only chỉ duyệt 8 cạnh hợp lệ và giữ 2 cạnh lỗi.
        - Thao tác hàng loạt không tự đổi các cạnh đã ở trạng thái Đã duyệt hoặc Loại bỏ.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facade = KGStudioFacade(
                json_repo=JsonProjectRepository(tmp_path / "projects"),
                sqlite_repo=SQLiteProjectRepository(tmp_path / "test.db"),
                vector_repo=VectorIndexRepository(tmp_path / "vectors"),
            )
            client = FrontendClient(facade=facade)
            project = _seed_curation_project("Batch_10_Edges")
            doc = project["documents"][0]
            _, pending_prop = propose_term(project, "relations", "tọa lạc cổ", "Nằm tại vị trí cổ", {"doc_id": doc["id"]})

            project["nodes"] = [
                {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": [doc["id"]]},
                {"id": "n2", "name": "quận Ba Đình", "kind": "địa điểm", "aliases": [], "documents": [doc["id"]]},
            ]
            project["edges"] = []
            # 8 cạnh hợp lệ (e1..e8) + 2 cạnh vướng đề xuất EDC chờ duyệt (e9, e10)
            for idx in range(1, 11):
                is_blocked = idx in (9, 10)
                project["edges"].append(
                    {
                        "id": f"e{idx}",
                        "source": "n1",
                        "target": "n2",
                        "relation": "tọa lạc cổ" if is_blocked else "nằm tại",
                        "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                        "evidence_found": True,
                        "doc_id": doc["id"],
                        "doc_name": doc["name"],
                        "doc_fingerprint": doc_fingerprint(doc),
                        "chunk_number": 1,
                        "status": STATUS_PENDING,
                        "schema_proposal_ids": [pending_prop] if is_blocked else [],
                    }
                )
            # Thêm 1 cạnh đã Loại bỏ (e_rej) và 1 cạnh Đã duyệt (e_app) để kiểm tra kịch bản 3
            project["edges"].append(
                {
                    "id": "e_rej",
                    "source": "n1",
                    "target": "n2",
                    "relation": "nằm tại",
                    "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                    "evidence_found": True,
                    "doc_id": doc["id"],
                    "status": STATUS_REJECTED,
                    "rejection_code": "duplicate_fact",
                }
            )
            facade.save_project(project)

            state: dict = {}
            for idx in range(1, 11):
                toggle_edge_selection(project, f"e{idx}", True, state)

            preview = build_edge_batch_preview(
                project,
                [f"e{idx}" for idx in range(1, 11)],
                "approve",
                client=client,
                state_store=state,
            )
            self.assertEqual(preview.valid_count, 8)
            self.assertEqual(preview.invalid_count, 2)
            self.assertFalse(preview.can_apply_all)
            self.assertTrue(preview.can_apply_valid_only)

            # all_or_nothing bị chặn
            with self.assertRaises(ValueError):
                execute_edge_batch_apply(project, apply_mode="all_or_nothing", client=client, state_store=state)

            # valid_only chỉ duyệt 8 cạnh hợp lệ, giữ lại 2 cạnh lỗi e9, e10 trong lựa chọn
            res = execute_edge_batch_apply(project, apply_mode="valid_only", client=client, state_store=state)
            self.assertEqual(res.applied_count, 8)
            self.assertEqual(res.skipped_count, 2)

            e_state = get_curation_section_state(project, "edges", state)
            self.assertEqual(set(e_state["selected_ids"]), {"e9", "e10"})

            # Kiểm tra Kịch bản 3: nếu cố gửi e_rej (Loại bỏ) hoặc e1 (Đã duyệt) vào lô hàng loạt -> bị chặn đổi trạng thái
            req_batch_flip = CurationReviewRequestDTO(
                project_id=project["project_id"],
                decisions=[
                    EdgeReviewDecisionDTO(edge_id="e1", action=STATUS_REJECTED, reason_code="other", note="Cố lật hàng loạt"),
                    EdgeReviewDecisionDTO(edge_id="e_rej", action=STATUS_APPROVED),
                ],
                apply_mode="valid_only",
                is_batch=True,
                expected_revision=facade.project_revision(project),
            )
            prev_flip = preview_curation_decisions(project, req_batch_flip)
            self.assertEqual(prev_flip.valid_count, 0)
            self.assertEqual(prev_flip.excluded_processed_count, 2)

    def test_03_missing_evidence_override_and_multi_occurrence_disambiguation(self) -> None:
        """Kịch bản 4 & 5:
        - Cạnh thiếu bằng chứng không được duyệt trong lô hàng loạt; chỉ được duyệt đơn lẻ khi có Lý do xác nhận ngoại lệ không rỗng.
        - Câu bằng chứng xuất hiện nhiều lần trong tài liệu: đánh dấu ambiguous=True và cho phép chọn đúng vị trí xuất hiện.
        """
        project = _seed_curation_project("Evidence_Rules")
        doc = project["documents"][0]
        project["nodes"] = [
            {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": [doc["id"]]},
            {"id": "n2", "name": "quận Ba Đình", "kind": "địa điểm", "aliases": [], "documents": [doc["id"]]},
        ]
        # e_missing có trích dẫn không tồn tại trong DOC_TEXT
        # e_multi có trích dẫn "Chùa Một Cột tọa lạc tại quận Ba Đình" xuất hiện 2 lần trong DOC_TEXT
        project["edges"] = [
            {
                "id": "e_missing",
                "source": "n1",
                "target": "n2",
                "relation": "nằm tại",
                "evidence": "Câu trích dẫn này hoàn toàn không có trong văn bản gốc",
                "evidence_found": False,
                "doc_id": doc["id"],
                "doc_name": doc["name"],
                "status": STATUS_CHECK,
            },
            {
                "id": "e_multi",
                "source": "n1",
                "target": "n2",
                "relation": "nằm tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                "evidence_found": True,
                "doc_id": doc["id"],
                "doc_name": doc["name"],
                "status": STATUS_PENDING,
            },
        ]

        # 1. Cạnh thiếu bằng chứng bị chặn trong lô hàng loạt dù có truyền override_reason
        batch_req = CurationReviewRequestDTO(
            project_id=project["project_id"],
            decisions=[EdgeReviewDecisionDTO(edge_id="e_missing", action=STATUS_APPROVED, override_reason="Cố duyệt lô")],
            is_batch=True,
        )
        batch_prev = preview_curation_decisions(project, batch_req)
        self.assertEqual(batch_prev.valid_count, 0)

        # Duyệt đơn lẻ thiếu override_reason -> bị chặn
        with self.assertRaises(ValueError):
            set_edge_status(project, "e_missing", STATUS_APPROVED, override_reason="")

        # Duyệt đơn lẻ có override_reason -> thành công và lưu override=True
        updated = set_edge_status(project, "e_missing", STATUS_APPROVED, override_reason="Xác nhận theo tài liệu phụ lục")
        self.assertEqual(updated["status"], STATUS_APPROVED)
        self.assertTrue(updated["override"])
        self.assertEqual(updated["override_reason"], "Xác nhận theo tài liệu phụ lục")

        # 2. Kịch bản 5: Câu bằng chứng xuất hiện 2 lần trong DOC_TEXT
        ctx_multi = evidence_context(project, project["edges"][1])
        self.assertTrue(ctx_multi["found"])
        self.assertTrue(ctx_multi["ambiguous"])
        self.assertEqual(len(ctx_multi["candidates"]), 2)

        # Chọn lần xuất hiện thứ 2
        second_cand = ctx_multi["candidates"][1]
        locked_ctx = select_edge_evidence_span(
            project,
            "e_multi",
            second_cand["start_char"],
            second_cand["end_char"],
        )
        self.assertFalse(locked_ctx["ambiguous"])
        self.assertEqual(locked_ctx["start_char"], second_cand["start_char"])
        self.assertEqual(locked_ctx["end_char"], second_cand["end_char"])

        # Kiểm tra HTML highlight an toàn với ký tự đặc biệt
        html_out = format_highlighted_evidence_html(locked_ctx)
        self.assertIn("<mark", html_out)
        self.assertIn("Chùa Một Cột tọa lạc tại quận Ba Đình", html_out)

        # Tài liệu txt không có pages -> không bịa số trang 1
        self.assertIsNone(locked_ctx["page"])
        rows = build_edge_table_rows(project, project["edges"], [])
        self.assertNotIn("Trang 1", rows[1]["source_location"])

    def test_04_post_approval_invalidation_and_edit_impact_matrix(self) -> None:
        """Kịch bản 6, 7 & 8:
        - Cạnh đã duyệt nhưng tài liệu nguồn hoặc danh mục thay đổi làm mất hiệu lực -> bị loại khỏi approved_graph và báo lỗi trong validate_integrity.
        - Sửa quan hệ hoặc thực thể đầu mút của cạnh đã duyệt (dù câu bằng chứng vẫn khớp) -> chuyển về Cần kiểm tra và xóa cờ phê duyệt cũ.
        - Sửa thông tin thực thể độc lập không cần gộp: giữ nguyên node_id, chặn loại ngoài danh mục, đổi loại thì hạ cạnh nối về Cần kiểm tra.
        """
        project = _seed_curation_project("Integrity_Matrix")
        doc = project["documents"][0]
        project["nodes"] = [
            {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": [doc["id"]]},
            {"id": "n2", "name": "quận Ba Đình", "kind": "địa điểm", "aliases": [], "documents": [doc["id"]]},
            {"id": "n3", "name": "Lý Thái Tông", "kind": "nhân vật", "aliases": [], "documents": [doc["id"]]},
        ]
        project["edges"] = [
            {
                "id": "e1",
                "source": "n1",
                "target": "n2",
                "relation": "nằm tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                "evidence_found": True,
                "doc_id": doc["id"],
                "doc_name": doc["name"],
                "doc_fingerprint": doc_fingerprint(doc),
                "status": STATUS_PENDING,
            }
        ]
        set_edge_status(project, "e1", STATUS_APPROVED)
        _, exp_edges = approved_graph(project)
        self.assertEqual(len(exp_edges), 1)
        self.assertEqual(validate_integrity(project), [])

        # Kịch bản 6: Đổi danh mục quan hệ làm "nằm tại" biến mất khỏi danh mục đã duyệt -> e1 mất hiệu lực xuất ở Trang 6
        saved_rels = copy.deepcopy(catalog_rows(project, "relations"))
        apply_relations(project, [{"name": "xây dựng năm", "description": "Năm", "definition": "Năm xây dựng"}])
        _, exp_edges_after_cat = approved_graph(project)
        self.assertEqual(len(exp_edges_after_cat), 0)
        problems = validate_integrity(project)
        self.assertTrue(any("mất hiệu lực" in p for p in problems))

        # Khôi phục danh mục
        apply_relations(project, saved_rels)
        self.assertEqual(len(approved_graph(project)[1]), 1)

        # Kịch bản 7: Sửa relation (hoặc target) của cạnh đã duyệt e1 trong khi câu bằng chứng vẫn khớp -> e1 phải về Cần kiểm tra
        update_edge(project, "e1", relation="gắn với nhân vật", target="n3")
        self.assertEqual(project["edges"][0]["status"], STATUS_CHECK)
        self.assertEqual(project["edges"][0]["reviewed_at"], "")
        self.assertFalse(project["edges"][0]["override"])

        # Duyệt lại e1 sau khi trả về đúng (n1, nằm tại, n2)
        update_edge(project, "e1", relation="nằm tại", target="n2")
        set_edge_status(project, "e1", STATUS_APPROVED)
        self.assertEqual(project["edges"][0]["status"], STATUS_APPROVED)

        # Kịch bản 8: Sửa tên, bí danh, mô tả của n1 -> giữ nguyên node_id="n1" và KHÔNG làm e1 mất trạng thái Đã duyệt
        update_node(
            project,
            "n1",
            name="Diên Hựu Tự",
            aliases=["Chùa Một Cột", "Liên Hoa Đài", "chùa một cột"],
            description="Ngôi chùa có kiến trúc hình bông sen",
        )
        self.assertEqual(project["nodes"][0]["id"], "n1")
        self.assertEqual(project["nodes"][0]["aliases"], ["Chùa Một Cột", "Liên Hoa Đài"])
        self.assertEqual(project["edges"][0]["status"], STATUS_APPROVED)

        # Chặn đặt loại ngoài danh mục đã duyệt
        with self.assertRaises(ValueError):
            update_node(project, "n1", kind="loại tự chế chưa duyệt")

        # Đổi loại của n1 sang loại khác trong danh mục ("địa điểm") -> cạnh e1 chuyển về Cần kiểm tra
        update_node(project, "n1", kind="địa điểm")
        self.assertEqual(project["edges"][0]["status"], STATUS_CHECK)

    def test_05_not_duplicate_pairs_and_merge_2_or_3_entities_with_conflicts_and_self_loops(self) -> None:
        """Kịch bản 9, 10, 11, 12, 13 & 14:
        - Đánh dấu Khác đối tượng không gợi ý lại trừ khi tên/bí danh thay đổi.
        - Gộp 2 và 3 thực thể: bảo toàn bí danh, tài liệu, đề xuất EDC, edc_observations, merged_from và node_redirects phẳng.
        - Gộp thực thể có cạnh nối trực tiếp -> sinh self-loop chuyển về Cần kiểm tra và không lọt sang đồ thị xuất.
        - Gộp thực thể khác loại -> bắt buộc chọn loại chuẩn + lý do; hạ cạnh của thực thể đổi loại về Cần kiểm tra.
        - Gộp tạo ra 2 cạnh cùng (source, relation, target) nhưng khác bằng chứng -> giữ nguyên cả 2 cạnh, không tự xóa!
        """
        project = _seed_curation_project("Entity_Merge_Scenarios")
        doc = project["documents"][0]
        _, prop_et = propose_term(project, "entity_types", "cổ tự", "Ngôi chùa cổ", {"doc_id": doc["id"]})
        decide_proposal(project, prop_et, "merge", canonical_name="di tích")

        project["nodes"] = [
            {
                "id": "n1",
                "name": "Chùa Một Cột",
                "kind": "di tích",
                "aliases": ["Chùa Mật"],
                "description": "Mô tả 1",
                "documents": [doc["id"]],
                "schema_proposal_ids": [prop_et],
                "edc_observations": [{"doc_id": doc["id"], "name": "Chùa Một Cột", "kind": "cổ tự"}],
            },
            {
                "id": "n2",
                "name": "chùa một cột",
                "kind": "di tích",
                "aliases": ["Diên Hựu"],
                "description": "Mô tả 2",
                "documents": ["doc_extra"],
                "schema_proposal_ids": [],
                "edc_observations": [{"doc_id": "doc_extra", "name": "chùa một cột", "kind": "di tích"}],
            },
            {
                "id": "n3",
                "name": "Liên Hoa Đài",
                "kind": "địa điểm",  # Khác loại để kiểm tra kịch bản 13 & gộp 3 thực thể
                "aliases": ["Chùa Một Cột"],
                "description": "Đài sen",
                "documents": [doc["id"]],
                "schema_proposal_ids": [],
                "edc_observations": [],
            },
            {
                "id": "n_badinh",
                "name": "quận Ba Đình",
                "kind": "địa điểm",
                "aliases": [],
                "description": "Quận trung tâm",
                "documents": [doc["id"]],
            },
        ]
        project["edges"] = [
            # Cạnh e_dup1 từ n1 -> n_badinh (Đã duyệt)
            {
                "id": "e_dup1",
                "source": "n1",
                "target": "n_badinh",
                "relation": "nằm tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.",
                "evidence_found": True,
                "doc_id": doc["id"],
                "status": STATUS_APPROVED,
            },
            # Cạnh e_dup2 từ n2 -> n_badinh có bằng chứng khác (Đã duyệt) -> sau khi gộp n2 vào n1 sẽ cùng (n1, nằm tại, n_badinh)
            {
                "id": "e_dup2",
                "source": "n2",
                "target": "n_badinh",
                "relation": "nằm tại",
                "evidence": "Về sau, Chùa Một Cột tọa lạc tại quận Ba Đình trở thành biểu tượng văn hóa",
                "evidence_found": True,
                "doc_id": doc["id"],
                "status": STATUS_APPROVED,
            },
            # Cạnh e_between nối trực tiếp n1 -> n2 (sẽ thành self-loop sau khi gộp)
            {
                "id": "e_between",
                "source": "n1",
                "target": "n2",
                "relation": "nằm tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                "evidence_found": True,
                "doc_id": doc["id"],
                "status": STATUS_APPROVED,
            },
            # Cạnh e_from_n3 từ n3 (loại địa điểm) -> n_badinh (Đã duyệt); khi n3 gộp về loại "di tích" thì cạnh này đổi loại đầu mút -> về Cần kiểm tra
            {
                "id": "e_from_n3",
                "source": "n3",
                "target": "n_badinh",
                "relation": "nằm tại",
                "evidence": "Hoàng thành Thăng Long nằm gần khu vực trung tâm quận Ba Đình.",
                "evidence_found": True,
                "doc_id": doc["id"],
                "status": STATUS_APPROVED,
            },
        ]

        # Kịch bản 9: Đánh dấu cặp (n1, n_badinh) hoặc (n1, n2) là Khác đối tượng
        sugs_before = duplicate_suggestions(project, fuzzy_threshold=0.80)
        pair_ids_before = {tuple(sorted([s["keep_id"], s["drop_id"]])) for s in sugs_before}
        self.assertIn(("n1", "n2"), pair_ids_before)

        mark_pair_not_duplicate(project, "n1", "n2", note="Giả sử khác đối tượng tạm thời")
        sugs_after_mark = duplicate_suggestions(project, fuzzy_threshold=0.80)
        pair_ids_after_mark = {tuple(sorted([s["keep_id"], s["drop_id"]])) for s in sugs_after_mark}
        self.assertNotIn(("n1", "n2"), pair_ids_after_mark)

        # Khi bí danh của n2 thay đổi -> cặp (n1, n2) được gợi ý lại!
        update_node(project, "n2", aliases=["Diên Hựu", "Bí danh mới"])
        sugs_after_alias_change = duplicate_suggestions(project, fuzzy_threshold=0.80)
        pair_ids_after_change = {tuple(sorted([s["keep_id"], s["drop_id"]])) for s in sugs_after_alias_change}
        self.assertIn(("n1", "n2"), pair_ids_after_change)

        # Kịch bản 13: Gộp 3 thực thể (n1, n2, n3) trong đó n3 khác loại mà thiếu kind_resolution_note -> bị chặn ở preview
        req_missing_kind_note = EntityMergeRequestDTO(
            project_id=project["project_id"],
            member_ids=["n1", "n2", "n3"],
            keep_id="n1",
            canonical_name="Chùa Một Cột",
            canonical_kind="di tích",
            kind_resolution_note="",  # Thiếu lý do giải quyết xung đột loại
            canonical_description="Mô tả gộp",
        )
        prev_bad = preview_entity_merge(project, req_missing_kind_note)
        self.assertFalse(prev_bad.valid)
        self.assertTrue(any("khác loại" in e for e in prev_bad.errors))

        # Cung cấp đầy đủ kind_resolution_note -> preview hợp lệ
        req_merge_3 = EntityMergeRequestDTO(
            project_id=project["project_id"],
            member_ids=["n1", "n2", "n3"],
            keep_id="n1",
            canonical_name="Chùa Một Cột",
            canonical_kind="di tích",
            kind_resolution_note="Liên Hoa Đài là kiến trúc đài sen thuộc di tích Chùa Một Cột",
            canonical_description="Mô tả tổng hợp Chùa Một Cột",
            expected_revision=compute_project_revision(project),
            request_id="merge_3_req",
        )
        prev_ok = preview_entity_merge(project, req_merge_3)
        self.assertTrue(prev_ok.valid)
        # Có 3 cạnh bị đổi đầu mút (e_dup2, e_between, e_from_n3): mỗi cạnh chỉ có 1 đầu mút thuộc {n2, n3} (riêng e_between có source=n1, target=n2)
        self.assertEqual(prev_ok.affected_edge_count, 3)
        self.assertIn("e_between", prev_ok.new_self_loop_ids)
        # Nhóm cạnh có vẻ trùng (n1, nằm tại, n_badinh) gồm e_dup1, e_dup2, e_from_n3
        self.assertEqual(len(prev_ok.apparent_duplicate_groups), 1)

        # Áp dụng gộp 3 thực thể thành 1
        _, merge_res = apply_entity_merge(project, req_merge_3, preview=prev_ok)
        self.assertEqual(merge_res.status, "committed")

        # Kịch bản 10 & 11: Chỉ còn n1 và n_badinh; n1 lưu đầy đủ merged_from (2 thực thể n2, n3), aliases, documents, observations và node_redirects phẳng
        remaining_ids = [n["id"] for n in project["nodes"]]
        self.assertEqual(remaining_ids, ["n1", "n_badinh"])
        kept_node = project["nodes"][0]
        self.assertIn("Diên Hựu", kept_node["aliases"])
        self.assertIn("Liên Hoa Đài", kept_node["aliases"])
        self.assertIn("doc_extra", kept_node["documents"])
        self.assertEqual(len(kept_node["merged_from"]), 2)
        self.assertEqual(len(kept_node["edc_observations"]), 2)
        self.assertEqual(project["node_redirects"], {"n2": "n1", "n3": "n1"})

        # Kịch bản 14: Không tự xóa mất bất kỳ cạnh nào (cả 4 cạnh vẫn còn nguyên ID và bằng chứng riêng)
        self.assertEqual(len(project["edges"]), 4)
        edges_by_id = {e["id"]: e for e in project["edges"]}
        self.assertEqual(edges_by_id["e_dup1"]["status"], STATUS_APPROVED)
        self.assertEqual(edges_by_id["e_dup2"]["status"], STATUS_APPROVED)
        self.assertNotEqual(edges_by_id["e_dup1"]["evidence"], edges_by_id["e_dup2"]["evidence"])
        dup_groups = compute_apparent_duplicate_edge_groups(project["edges"])
        self.assertEqual(len(dup_groups), 1)
        self.assertEqual(dup_groups[0]["count"], 3)

        # Kịch bản 12: Cạnh e_between trở thành tự nối (n1 -> n1) -> tự động về Cần kiểm tra và không xuất sang approved_graph
        self.assertEqual(edges_by_id["e_between"]["source"], "n1")
        self.assertEqual(edges_by_id["e_between"]["target"], "n1")
        self.assertEqual(edges_by_id["e_between"]["status"], STATUS_CHECK)
        self.assertFalse(is_edge_exportable(project, edges_by_id["e_between"]))

        # Kịch bản 13: Cạnh e_from_n3 nối với n3 (đổi từ địa điểm -> di tích) tự động chuyển về Cần kiểm tra
        self.assertEqual(edges_by_id["e_from_n3"]["status"], STATUS_CHECK)

    def test_06_non_semantic_rejection_codes_excluded_from_exporter_and_cross_page_nav(self) -> None:
        """Kịch bản 15 & 16:
        - Cạnh bị loại bỏ với lý do 'out_of_scope' hoặc 'duplicate_fact' không bị xuất làm mẫu âm ngữ nghĩa cho bộ huấn luyện.
        - Điều hướng từ cạnh/thực thể bị chặn ở Trang 5 sang đúng proposal_id ở Trang 4 và quay lại đúng mục ở Trang 5.
        """
        with tempfile.TemporaryDirectory() as tmp:
            exporter = ActiveLearningExporter(Path(tmp) / "exports")
            project = _seed_curation_project("Exporter_And_Nav")
            doc = project["documents"][0]
            _, p_block = propose_term(project, "relations", "tọa lạc tại", "Vị trí", {"doc_id": doc["id"]})

            project["nodes"] = [
                {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": [doc["id"]]},
                {"id": "n2", "name": "quận Ba Đình", "kind": "địa điểm", "aliases": [], "documents": [doc["id"]]},
                {"id": "n3", "name": "1049", "kind": "niên đại", "aliases": [], "documents": [doc["id"]]},
            ]
            project["edges"] = [
                {
                    "id": "e_pos",
                    "source": "n1",
                    "target": "n2",
                    "relation": "nằm tại",
                    "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                    "evidence_found": True,
                    "doc_id": doc["id"],
                    "chunk_hash": "chunk_1",
                    "status": STATUS_APPROVED,
                },
                {
                    "id": "e_dup_rej",
                    "source": "n1",
                    "target": "n3",
                    "relation": "xây dựng năm",
                    "evidence": "Năm 1049, vua Lý Thái Tông cho xây dựng Chùa Một Cột.",
                    "evidence_found": True,
                    "doc_id": doc["id"],
                    "chunk_hash": "chunk_1",
                    "status": STATUS_REJECTED,
                    "rejection_code": "duplicate_fact",
                    "review_note": "Trùng dữ kiện đã có",
                },
                {
                    "id": "e_scope_rej",
                    "source": "n1",
                    "target": "n3",
                    "relation": "gắn với nhân vật",
                    "evidence": "Năm 1049, vua Lý Thái Tông cho xây dựng Chùa Một Cột.",
                    "evidence_found": True,
                    "doc_id": doc["id"],
                    "chunk_hash": "chunk_1",
                    "status": STATUS_REJECTED,
                    "rejection_code": "out_of_scope",
                    "review_note": "Ngoài phạm vi",
                },
            ]

            # Vì cả "xây dựng năm" (duplicate_fact) và "gắn với nhân vật" (out_of_scope) đều bị loại vì lý do phi ngữ nghĩa,
            # không được phép xuất chúng làm mẫu âm ngữ nghĩa cho chunk_1!
            triplets = exporter.build_sr_triplets(project)
            for t in triplets:
                self.assertNotIn(t.negative_name, {"xây dựng năm", "gắn với nhân vật"})

            # Nếu có 1 cạnh bị loại vì lý do ngữ nghĩa ("wrong_relation_or_direction") -> được dùng làm hard negative
            project["edges"][1]["rejection_code"] = "wrong_relation_or_direction"
            triplets_sem = exporter.build_sr_triplets(project)
            self.assertEqual(len(triplets_sem), 1)
            self.assertEqual(triplets_sem[0].negative_name, "xây dựng năm")

            # Kịch bản 16: Điều hướng từ cạnh bị chặn ở Trang 5 sang đúng proposal_id ở Trang 4 và quay lại Trang 5
            state: dict = {}
            nav_ctx = navigate_to_edc_proposal_from_curation(
                project,
                p_block,
                edge_id="e_pos",
                section="edges",
                state_store=state,
            )
            self.assertEqual(state["active_page"], PAGE_LABELS[3])
            self.assertEqual(get_edc_table_state(project, "relations", state)["focused_proposal_id"], p_block)
            self.assertEqual(nav_ctx["edge_id"], "e_pos")

            ret_ctx = return_to_curation_from_edc(project, state_store=state)
            self.assertIsNotNone(ret_ctx)
            self.assertEqual(state["active_page"], PAGE_LABELS[3])
            self.assertEqual(get_curation_section_state(project, "edges", state)["focused_edge_id"], "e_pos")

    def test_07_transactional_concurrency_idempotency_io_rollback_sqlite_resync_and_snapshot_restore(self) -> None:
        """Kịch bản 17, 18, 19 & REST API:
        - Đa phiên cùng sửa hoặc đổi danh mục sau bước xem trước -> bị chặn ghi đè.
        - Nhấn đúp cùng request_id không tạo lịch sử/snapshot trùng; cùng request_id khác nội dung bị từ chối.
        - Lỗi I/O giữa các lần ghi JSON khôi phục nguyên trạng bộ file.
        - Lỗi SQLite sau khi ghi JSON đánh dấu sync_pending và đồng bộ lại thành công.
        - Khôi phục snapshot trước khi gộp thực thể khôi phục đầy đủ thực thể đã gộp, trạng thái cạnh và SQLite.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facade = KGStudioFacade(
                json_repo=JsonProjectRepository(tmp_path / "projects"),
                sqlite_repo=SQLiteProjectRepository(tmp_path / "test.db"),
                vector_repo=VectorIndexRepository(tmp_path / "vectors"),
            )
            project = _seed_curation_project("Tx_Curation")
            doc = project["documents"][0]
            project["nodes"] = [
                {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": [doc["id"]]},
                {"id": "n2", "name": "Chùa Mật", "kind": "di tích", "aliases": [], "documents": [doc["id"]]},
                {"id": "n3", "name": "quận Ba Đình", "kind": "địa điểm", "aliases": [], "documents": [doc["id"]]},
            ]
            project["edges"] = [
                {
                    "id": "e1",
                    "source": "n2",
                    "target": "n3",
                    "relation": "nằm tại",
                    "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                    "evidence_found": True,
                    "doc_id": doc["id"],
                    "doc_fingerprint": doc_fingerprint(doc),
                    "status": STATUS_PENDING,
                }
            ]
            facade.save_project(project)

            s1 = facade.load_project("Tx_Curation")
            s2 = facade.load_project("Tx_Curation")

            req_s1 = CurationReviewRequestDTO(
                project_id=s1["project_id"],
                decisions=[EdgeReviewDecisionDTO(edge_id="e1", action=STATUS_APPROVED)],
                expected_revision=facade.project_revision(s1),
                request_id="cur_req_1",
            )
            req_s2 = CurationReviewRequestDTO(
                project_id=s2["project_id"],
                decisions=[EdgeReviewDecisionDTO(edge_id="e1", action=STATUS_CHECK)],
                expected_revision=facade.project_revision(s2),
                request_id="cur_req_2",
            )

            # Phiên 1 commit thành công
            res_1 = facade.apply_curation_decisions(s1, req_s1)
            self.assertEqual(res_1.status, "committed")
            self.assertEqual(res_1.applied_count, 1)

            # Nhấn đúp cùng request_id -> idempotent_replay=True, không sinh thêm snapshot
            snaps_before = len(facade.list_snapshots(s1))
            res_1_dup = facade.apply_curation_decisions(s1, req_s1)
            self.assertTrue(res_1_dup.idempotent_replay)
            self.assertEqual(len(facade.list_snapshots(s1)), snaps_before)

            # Cùng request_id nhưng đổi nội dung -> từ chối
            req_1_tampered = copy.deepcopy(req_s1)
            req_1_tampered.decisions[0].action = STATUS_REJECTED
            with self.assertRaises(ValueError):
                facade.apply_curation_decisions(s1, req_1_tampered)

            # Phiên 2 commit với expected_revision cũ -> bị chặn
            with self.assertRaises(ValueError):
                facade.apply_curation_decisions(s2, req_s2)

            # Giả lập lỗi I/O giữa chừng khi gộp thực thể -> rollback bộ file JSON
            write_calls = 0

            def _flaky_writer(path: Path, data: bytes) -> None:
                nonlocal write_calls
                write_calls += 1
                if write_calls == 2:
                    raise OSError("Lỗi ghi đĩa giả lập")
                atomic_write(path, data)

            facade.json_repo._writer_fn = _flaky_writer
            merge_req = EntityMergeRequestDTO(
                project_id=s1["project_id"],
                member_ids=["n1", "n2"],
                keep_id="n1",
                canonical_name="Chùa Một Cột",
                canonical_kind="di tích",
                expected_revision=facade.project_revision(s1),
                request_id="merge_io_fail",
            )
            with self.assertRaises(OSError):
                facade.apply_entity_merge(s1, merge_req)

            # Khôi phục writer chuẩn và kiểm tra n2 vẫn còn nguyên trên đĩa
            facade.json_repo._writer_fn = atomic_write
            reloaded = facade.load_project("Tx_Curation")
            self.assertEqual(len(reloaded["nodes"]), 3)

            # Giả lập lỗi SQLite khi gộp thực thể -> JSON vẫn commit kèm sync_pending=True
            orig_sync = facade.sqlite_repo.sync_from_project_dict

            def _broken_sqlite(proj_dict: dict) -> None:
                raise RuntimeError("SQLite busy")

            facade.sqlite_repo.sync_from_project_dict = _broken_sqlite  # type: ignore[assignment]
            merge_req_ok = EntityMergeRequestDTO(
                project_id=reloaded["project_id"],
                member_ids=["n1", "n2"],
                keep_id="n1",
                canonical_name="Chùa Một Cột",
                canonical_kind="di tích",
                expected_revision=facade.project_revision(reloaded),
                request_id="merge_sqlite_pending",
            )
            res_merge = facade.apply_entity_merge(reloaded, merge_req_ok)
            self.assertEqual(res_merge.status, "committed")
            self.assertEqual(res_merge.sync_status, "sync_pending")
            self.assertEqual(len(reloaded["nodes"]), 2)

            # Đồng bộ lại SQLite thành công
            facade.sqlite_repo.sync_from_project_dict = orig_sync  # type: ignore[assignment]
            sync_res = facade.resync_sqlite(reloaded)
            self.assertEqual(sync_res["status"], "synced")
            self.assertFalse(reloaded.get("sync_pending"))

            # Kịch bản 19: Khôi phục snapshot trước khi gộp thực thể -> n2 quay trở lại và cạnh e1 trỏ lại về n2
            facade.restore_snapshot(reloaded, Path(res_merge.snapshot_path))
            self.assertEqual(len(reloaded["nodes"]), 3)
            self.assertEqual(reloaded["edges"][0]["source"], "n2")

            # Kiểm tra REST API /curation/preview-merge, /apply-merge, /edit-entity, /edit-edge và chặn sai project_id
            bad_code, _ = handle_api_request(
                "POST",
                "/api/v1/projects/Tx_Curation/curation/preview-edges",
                {"project_id": "WRONG_ID", "decisions": []},
                facade=facade,
            )
            self.assertEqual(bad_code, 400)

            code_prev, resp_prev = handle_api_request(
                "POST",
                "/api/v1/projects/Tx_Curation/curation/preview-merge",
                {
                    "project_id": reloaded["project_id"],
                    "member_ids": ["n1", "n2"],
                    "keep_id": "n1",
                    "canonical_name": "Chùa Một Cột",
                    "canonical_kind": "di tích",
                },
                facade=facade,
            )
            self.assertEqual(code_prev, 200)
            self.assertTrue(resp_prev["preview"]["valid"])

    def test_bulk_entity_merges_with_dsu_clustering(self) -> None:
        """Kiểm tra gộp hàng loạt thực thể với DSU clustering kết nối chuỗi A-B và B-C."""
        project = _seed_curation_project("Bulk_Merge_Test")
        project["nodes"] = [
            {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": ["Diên Hựu"], "documents": ["doc1"]},
            {"id": "n2", "name": "chùa Một Cột", "kind": "di tích", "aliases": [], "documents": ["doc1"]},
            {"id": "n3", "name": "Di tích Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": ["doc1"]},
            {"id": "n4", "name": "Hồ Hoàn Kiếm", "kind": "địa danh", "aliases": ["Bờ Hồ"], "documents": ["doc1"]},
            {"id": "n5", "name": "Hồ Gươm", "kind": "địa danh", "aliases": [], "documents": ["doc2"]},
        ]
        project["edges"] = [
            {
                "id": "e_bulk_0",
                "source": "n1",
                "target": "n4",
                "relation": "nằm tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.",
                "doc_id": "doc1",
                "status": STATUS_PENDING,
            },
            {
                "id": "e_bulk_1",
                "source": "n4",
                "target": "n1",
                "relation": "nằm tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.",
                "doc_id": "doc1",
                "status": STATUS_PENDING,
            },
            {
                "id": "e_bulk_2",
                "source": "n5",
                "target": "n3",
                "relation": "nằm tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.",
                "doc_id": "doc1",
                "status": STATUS_PENDING,
            },
        ]

        pairs = [("n2", "n1"), ("n3", "n2"), ("n4", "n5")]
        _, res = apply_bulk_entity_merges(project, pairs)
        self.assertEqual(res.status, "applied")
        self.assertEqual(res.applied_count, 3)

        redirects = project.get("node_redirects", {})
        self.assertEqual(redirects.get("n2"), "n1")
        self.assertEqual(redirects.get("n3"), "n1")
        self.assertEqual(redirects.get("n5"), "n4")

        e2 = next(e for e in project["edges"] if e["id"] == "e_bulk_2")
        self.assertEqual(e2["source"], "n4")
        self.assertEqual(e2["target"], "n1")

        remaining_ids = {n["id"] for n in project["nodes"]}
        self.assertIn("n1", remaining_ids)
        self.assertIn("n4", remaining_ids)
        self.assertNotIn("n2", remaining_ids)
        self.assertNotIn("n3", remaining_ids)
        self.assertNotIn("n5", remaining_ids)

    def test_relation_duplicate_suggestions_and_dismiss(self) -> None:
        """Kiểm tra phát hiện quan hệ nghi trùng theo chuẩn hóa và fuzzy similarity."""
        project = _seed_curation_project("Rel_Dup_Test")
        project["edges"].extend([
            {"id": "er1", "source": "n1", "target": "n3", "relation": "nam_tai", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
            {"id": "er2", "source": "n1", "target": "n3", "relation": "nam_tai", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
            {"id": "er3", "source": "n1", "target": "n3", "relation": "co_dien_tich", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
            {"id": "er4", "source": "n1", "target": "n3", "relation": "có diện tích", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
        ])

        sugs = relation_duplicate_suggestions(project, fuzzy_threshold=0.65)
        self.assertTrue(len(sugs) >= 1)

        found_nam_tai = any(
            (s["relation_a"] in ("nam_tai", "nằm tại") and s["relation_b"] in ("nam_tai", "nằm tại"))
            for s in sugs
        )
        self.assertTrue(found_nam_tai)

        mark_relation_pair_not_duplicate(project, "nam_tai", "nằm tại")
        sugs_after = relation_duplicate_suggestions(project, fuzzy_threshold=0.65)
        found_nam_tai_after = any(
            (s["relation_a"] in ("nam_tai", "nằm tại") and s["relation_b"] in ("nam_tai", "nằm tại"))
            for s in sugs_after
        )
        self.assertFalse(found_nam_tai_after)

    def test_apply_relation_merge_and_bulk_apply(self) -> None:
        """Kiểm tra gộp quan hệ đơn lẻ và gộp quan hệ hàng loạt."""
        project = _seed_curation_project("Rel_Merge_Test")
        project["edges"].extend([
            {"id": "er1", "source": "n1", "target": "n3", "relation": "nam_tai", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
            {"id": "er2", "source": "n1", "target": "n3", "relation": "co_dien_tich", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
            {"id": "er3", "source": "n1", "target": "n3", "relation": "dien_tich", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
        ])

        # Kiểm tra lưu alias sau khi gộp quan hệ đơn lẻ
        _, res1 = apply_relation_merge(project, ["nam_tai"], "nằm tại")
        self.assertEqual(res1.status, "applied")
        e1 = next(e for e in project["edges"] if e["id"] == "er1")
        self.assertEqual(e1["relation"], "nằm tại")
        self.assertEqual(project.get("relation_redirects", {}).get("nam_tai"), "nằm tại")
        self.assertIn("nam_tai", project.get("relation_aliases", {}).get("nằm tại", []))

        # Kiểm tra khi collapse_edges=False thì e3 vẫn được giữ lại với tên mới
        proj_no_col = copy.deepcopy(project)
        _, res_no_col = bulk_apply_relation_merges(proj_no_col, {"dien_tich": "co_dien_tich"}, collapse_edges=False)
        e3_keep = next(e for e in proj_no_col["edges"] if e["id"] == "er3")
        self.assertEqual(e3_keep["relation"], "co_dien_tich")

        # Kiểm tra khi collapse_edges=True (mặc định): er3 và er2 có cùng bộ ba nên er3 được gộp thông minh vào er2
        _, res2 = bulk_apply_relation_merges(project, {"dien_tich": "co_dien_tich"}, collapse_edges=True)
        self.assertEqual(res2.status, "applied")
        self.assertEqual(res2.merged_duplicate_edges, 1)
        self.assertEqual(project.get("edge_redirects", {}).get("er3"), "er2")
        e2 = next(e for e in project["edges"] if e["id"] == "er2")
        self.assertEqual(e2["relation"], "co_dien_tich")
        self.assertIn("dien_tich", e2.get("original_relations", []))
        self.assertEqual(len(e2.get("evidences", [])), 2)
        self.assertEqual(project.get("relation_redirects", {}).get("dien_tich"), "co_dien_tich")
        self.assertIn("dien_tich", project.get("relation_aliases", {}).get("co_dien_tich", []))

        # Kiểm tra sau khi gộp, các quan hệ đã gộp (nam_tai, dien_tich) bị ẩn hoàn toàn khỏi danh sách gợi ý
        sugs_after_merge = relation_duplicate_suggestions(project, fuzzy_threshold=0.65)
        for s in sugs_after_merge:
            self.assertNotIn(s["relation_a"], ("nam_tai", "dien_tich"))
            self.assertNotIn(s["relation_b"], ("nam_tai", "dien_tich"))

    def test_facade_and_client_bulk_merges(self) -> None:
        """Kiểm tra gọi apply_bulk_entity_merges và bulk_apply_relation_merges qua Facade và Client không lỗi sha/json."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_repo = JsonProjectRepository(Path(tmp_dir) / "projects")
            sqlite_repo = SQLiteProjectRepository(db_path=Path(tmp_dir) / "test.db")
            facade = KGStudioFacade(json_repo=json_repo, sqlite_repo=sqlite_repo)
            client = FrontendClient(facade=facade)

            project = _seed_curation_project("Facade_Bulk_Merge_Test")
            project["nodes"] = [
                {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "aliases": [], "documents": ["doc1"]},
                {"id": "n2", "name": "chùa Một Cột", "kind": "di tích", "aliases": [], "documents": ["doc1"]},
            ]
            project["edges"] = [
                {"id": "e1", "source": "n1", "target": "n2", "relation": "nằm tại", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
                {"id": "e2", "source": "n2", "target": "n1", "relation": "nam_tai", "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội.", "doc_id": "doc1", "status": STATUS_PENDING},
            ]
            json_repo.save_project(project)

            # 1. Gọi client.apply_bulk_entity_merges
            res_ent = client.apply_bulk_entity_merges(project, [("n1", "n2")])
            self.assertEqual(res_ent.status, "applied")
            self.assertEqual(res_ent.applied_count, 1)
            self.assertEqual(project.get("name"), "Facade_Bulk_Merge_Test")

            # 2. Gọi client.bulk_apply_relation_merges
            res_rel = client.bulk_apply_relation_merges(project, {"nam_tai": "nằm tại"})
            self.assertEqual(res_rel.status, "applied")
            self.assertEqual(res_rel.applied_count, 1)
            self.assertEqual(project.get("name"), "Facade_Bulk_Merge_Test")

            # 3. Gọi client.apply_relation_merge
            project["edges"].append({"id": "e3", "source": "n1", "target": "n1", "relation": "nam_tai", "evidence": "bằng chứng", "doc_id": "doc1", "status": STATUS_PENDING})
            res_single_rel = client.apply_relation_merge(project, ["nam_tai"], "nằm tại")
            self.assertEqual(res_single_rel.status, "applied")
            self.assertEqual(project.get("name"), "Facade_Bulk_Merge_Test")

            # 4. Gọi client.collapse_duplicate_edges trực tiếp (đảm bảo không bị KeyError 'name' hay rỗng dict)
            project["edges"].append({"id": "e4", "source": "n1", "target": "n1", "relation": "nằm tại", "evidence": "bằng chứng thứ hai", "doc_id": "doc1", "status": STATUS_APPROVED})
            res_collapse = client.collapse_duplicate_edges(project)
            self.assertEqual(res_collapse.status, "applied")
            self.assertGreaterEqual(res_collapse.merged_duplicate_edges, 1)
            self.assertEqual(project.get("name"), "Facade_Bulk_Merge_Test")
            self.assertIn("name", project)

    def test_collapse_duplicate_edges_standalone(self) -> None:
        """Kiểm tra hàm collapse_duplicate_edges hợp nhất đúng cạnh, dồn evidences và cập nhật edge_redirects."""
        project = _seed_curation_project("Collapse_Edges_Test")
        project["edges"] = [
            {"id": "c1", "source": "node_a", "target": "node_b", "relation": "nằm tại", "evidence": "Câu bằng chứng ngắn.", "doc_id": "d1", "status": STATUS_PENDING},
            {"id": "c2", "source": "node_a", "target": "node_b", "relation": "nằm tại", "evidence": "Câu bằng chứng rất dài và đầy đủ ngữ cảnh lịch sử.", "doc_id": "d2", "status": STATUS_APPROVED},
            {"id": "c3", "source": "node_a", "target": "node_b", "relation": "nằm tại", "evidence": "Câu bằng chứng thứ ba từ nguồn khác.", "doc_id": "d3", "status": STATUS_CHECK},
            {"id": "c4", "source": "node_x", "target": "node_y", "relation": "khác", "evidence": "Cạnh độc lập.", "doc_id": "d1", "status": STATUS_APPROVED},
        ]

        candidate, dropped_count, records = collapse_duplicate_edges(project, actor="reviewer_test")
        self.assertEqual(dropped_count, 2)
        self.assertEqual(len(candidate["edges"]), 2)
        
        # Cạnh giữ lại phải là c2 vì có status=STATUS_APPROVED và evidence dài nhất
        kept_edge = next(e for e in candidate["edges"] if e["source"] == "node_a")
        self.assertEqual(kept_edge["id"], "c2")
        self.assertEqual(kept_edge["status"], STATUS_APPROVED)
        self.assertEqual(len(kept_edge.get("evidences", [])), 3)

        # Kiểm tra edge_redirects
        self.assertEqual(candidate["edge_redirects"]["c1"], "c2")
        self.assertEqual(candidate["edge_redirects"]["c3"], "c2")

    def test_three_tier_curation_pipeline_flow(self) -> None:
        """Kiểm tra tường minh luồng 3 bước độc lập:
        Bước 1: Gộp thực thể B -> A (rewire cạnh)
        Bước 2: Gộp quan hệ 'tọa lạc ở', 'ở' -> 'nằm tại' (đổi tên nhãn)
        Bước 3: Gộp cạnh / Khử trùng bộ ba (dồn bằng chứng, xóa đúng cạnh trùng, bảo toàn cạnh không trùng)
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_repo = JsonProjectRepository(Path(tmp_dir) / "projects")
            sqlite_repo = SQLiteProjectRepository(db_path=Path(tmp_dir) / "test.db")
            facade = KGStudioFacade(json_repo=json_repo, sqlite_repo=sqlite_repo)
            client = FrontendClient(facade=facade)

            project = _seed_curation_project("Three_Tier_Pipeline_Test")
            project["nodes"] = [
                {"id": "node_A", "name": "Hà Nội", "kind": "Địa danh", "aliases": [], "documents": ["d1"]},
                {"id": "node_B", "name": "Ha Noi", "kind": "Địa danh", "aliases": [], "documents": ["d1"]},
                {"id": "node_C", "name": "Việt Nam", "kind": "Quốc gia", "aliases": [], "documents": ["d1"]},
                {"id": "node_D", "name": "Đồng bằng Sông Hồng", "kind": "Khu vực", "aliases": [], "documents": ["d1"]},
            ]
            project["edges"] = [
                {"id": "e1", "source": "node_A", "target": "node_C", "relation": "nằm tại", "evidence": "Hà Nội nằm tại Việt Nam.", "doc_id": "d1", "status": STATUS_APPROVED},
                {"id": "e2", "source": "node_B", "target": "node_C", "relation": "nằm tại", "evidence": "Ha Noi nằm tại Việt Nam theo tài liệu 2.", "doc_id": "d2", "status": STATUS_PENDING},
                {"id": "e3", "source": "node_A", "target": "node_D", "relation": "tọa lạc ở", "evidence": "Hà Nội tọa lạc ở Đồng bằng Sông Hồng.", "doc_id": "d1", "status": STATUS_CHECK},
                {"id": "e4", "source": "node_A", "target": "node_D", "relation": "ở", "evidence": "Hà Nội ở Đồng bằng Sông Hồng theo văn bản khác.", "doc_id": "d3", "status": STATUS_APPROVED},
                {"id": "e5", "source": "node_A", "target": "node_D", "relation": "thuộc", "evidence": "Hà Nội thuộc Đồng bằng Sông Hồng.", "doc_id": "d1", "status": STATUS_APPROVED},
                {"id": "e6", "source": "node_C", "target": "node_D", "relation": "ở", "evidence": "Việt Nam ở khu vực Đồng bằng Sông Hồng.", "doc_id": "d1", "status": STATUS_PENDING},
            ]
            json_repo.save_project(project)
            self.assertEqual(len(project["edges"]), 6)

            # --- BƯỚC 1: GỘP THỰC THỂ (node_B -> node_A) ---
            # Chỉ nối lại đầu mút, bảo toàn toàn bộ cạnh (collapse_edges=False)
            res_e = client.apply_bulk_entity_merges(project, [("node_A", "node_B")], collapse_edges=False)
            self.assertEqual(res_e.applied_count, 1)
            self.assertEqual(len(project["edges"]), 6)
            # e2 đã được nối lại sang node_A, tạo thành bộ ba (node_A, nằm tại, node_C) giống e1
            e2 = next(e for e in project["edges"] if e["id"] == "e2")
            self.assertEqual(e2["source"], "node_A")

            # --- BƯỚC 2: GỘP QUAN HỆ ('tọa lạc ở', 'ở' -> 'nằm tại') ---
            # Chỉ đổi nhãn quan hệ, bảo toàn toàn bộ cạnh (collapse_edges=False)
            res_r = client.bulk_apply_relation_merges(
                project, {"tọa lạc ở": "nằm tại", "ở": "nằm tại"}, collapse_edges=False
            )
            self.assertEqual(res_r.applied_count, 2)
            self.assertEqual(len(project["edges"]), 6)
            # e3, e4 và e6 đã được đổi tên quan hệ
            e3 = next(e for e in project["edges"] if e["id"] == "e3")
            e4 = next(e for e in project["edges"] if e["id"] == "e4")
            e5 = next(e for e in project["edges"] if e["id"] == "e5")
            e6 = next(e for e in project["edges"] if e["id"] == "e6")
            self.assertEqual(e3["relation"], "nằm tại")
            self.assertEqual(e4["relation"], "nằm tại")
            self.assertEqual(e5["relation"], "thuộc") # Quan hệ khác giữ nguyên
            self.assertEqual(e6["relation"], "nằm tại")

            # --- BƯỚC 3: GỘP CẠNH / KHỬ TRÙNG BỘ BA (Triple Deduplication) ---
            # Kiểm tra phát hiện đúng 2 nhóm trùng:
            # Nhóm 1: (node_A, nằm tại, node_C) -> gồm e1 và e2 (2 cạnh)
            # Nhóm 2: (node_A, nằm tại, node_D) -> gồm e3 và e4 (2 cạnh)
            # Các cạnh độc lập: e5 (thuộc), e6 (nguồn node_C)
            dup_groups = compute_apparent_duplicate_edge_groups(project.get("edges", []))
            self.assertEqual(len(dup_groups), 2)
            total_dup = sum(g.get("count", 1) - 1 for g in dup_groups)
            self.assertEqual(total_dup, 2)

            # Thực thi gộp cạnh qua client.collapse_duplicate_edges
            res_c = client.collapse_duplicate_edges(project)
            self.assertEqual(res_c.status, "applied")
            self.assertEqual(res_c.merged_duplicate_edges, 2)
            
            # Số cạnh sau khi dọn sạch từ 6 cạnh giảm xuống đúng 4 cạnh
            self.assertEqual(len(project["edges"]), 4)
            remaining_ids = {e["id"] for e in project["edges"]}
            
            # e1 được giữ lại (do status=APPROVED), e2 bị gộp vào e1
            self.assertIn("e1", remaining_ids)
            self.assertNotIn("e2", remaining_ids)
            kept_e1 = next(e for e in project["edges"] if e["id"] == "e1")
            self.assertEqual(len(kept_e1.get("evidences", [])), 2)

            # e4 được giữ lại (do status=APPROVED cao hơn CHECK của e3), e3 bị gộp vào e4
            self.assertIn("e4", remaining_ids)
            self.assertNotIn("e3", remaining_ids)
            kept_e4 = next(e for e in project["edges"] if e["id"] == "e4")
            self.assertEqual(len(kept_e4.get("evidences", [])), 2)

            # Cạnh không trùng e5 và e6 hoàn toàn bảo toàn nguyên vẹn
            self.assertIn("e5", remaining_ids)
            self.assertIn("e6", remaining_ids)

            # Kiểm tra edge_redirects lưu đúng ánh xạ
            self.assertEqual(project["edge_redirects"]["e2"], "e1")
            self.assertEqual(project["edge_redirects"]["e3"], "e4")


if __name__ == "__main__":
    unittest.main()
