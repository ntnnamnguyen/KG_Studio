"""Kiểm thử toàn diện tính năng Tách bảng và Duyệt EDC Hàng loạt (theo đặc tả edc-bulk-review.md)."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from backend.api.v1 import handle_api_request
from backend.domain.catalogs.service import (
    apply_proposal_decisions,
    catalog_rows,
    compute_project_revision,
    decide_proposal,
    is_proposal_candidates_stale,
    preview_proposal_decisions,
    proposal_impact,
    propose_term,
    schema_review_issue,
)
from backend.domain.curation.service import set_edge_status
from backend.domain.dataset_exporter.exporter import ActiveLearningExporter
from backend.domain.graph.service import approved_graph
from backend.domain.schema_intelligence.aligner import TargetAligner
from backend.facade import KGStudioFacade
from backend.integrations.embedder_gateway import EmbedderGateway
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from frontend.client import FrontendClient
from frontend.components.edc_bulk_actions import build_preview_for_scope, execute_batch_apply
from frontend.components.edc_review_table import (
    build_table_display_rows,
    compute_filter_signature,
    filter_and_sort_proposals,
    paginate_proposals,
)
from frontend.pages.p04_edc_alignment import compute_edc_overview_counts
from frontend.state.session import (
    assign_shared_target_to_drafts,
    clear_proposal_selection,
    fill_top1_candidate_to_drafts,
    get_edc_table_state,
    reconcile_selection_with_filter,
    reset_edc_state_if_project_changed,
    select_all_filtered_proposals,
    select_page_proposals,
    set_focused_proposal,
    toggle_proposal_selection,
    update_proposal_draft,
)
from shared.catalog_utils import apply_relations, atomic_write
from shared.constants import MODE_EDC_PLUS_R, STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.schemas.edc import BulkReviewRequestDTO, ProposalDecisionDTO


def _seed_edc_project(name: str = "EDC_Bulk_Test") -> dict:
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
                "description": "Năm xây dựng",
                "definition": "Công trình nguồn được khởi dựng vào năm đích.",
            },
        ],
    )
    project["entity_types"] = [
        {
            "name": "di tích",
            "description": "Công trình di sản",
            "definition": "Công trình văn hóa lịch sử được xếp hạng.",
        },
        {
            "name": "địa điểm",
            "description": "Khu vực địa lý",
            "definition": "Đơn vị hành chính hoặc địa danh.",
        },
    ]
    return project


class EDCBulkReviewTests(unittest.TestCase):
    def test_01_two_independent_tables_selection_sort_pagination_and_filter_pruning(self) -> None:
        """Kiểm tra tách 2 bảng độc lập, chọn một/nhiều/trang/tất cả theo ID, đổi trang/sắp xếp, đổi bộ lọc và đổi dự án."""
        project = _seed_edc_project("Proj_A")
        state: dict = {}

        # Tạo 5 đề xuất loại thực thể và 4 đề xuất quan hệ
        et_ids: list[str] = []
        for idx in range(1, 6):
            _, pid = propose_term(
                project,
                "entity_types",
                f"loại mở {idx}",
                f"Định nghĩa loại {idx}" if idx <= 4 else "",
                {"doc_id": "doc_1" if idx <= 3 else "doc_2", "example": f"Thực thể {idx}"},
            )
            et_ids.append(pid)

        rel_ids: list[str] = []
        for idx in range(1, 5):
            _, pid = propose_term(
                project,
                "relations",
                f"quan hệ mở {idx}",
                f"Định nghĩa quan hệ {idx}",
                {"doc_id": "doc_1", "example": f"A -> B ({idx})"},
            )
            rel_ids.append(pid)

        counts = compute_edc_overview_counts(project)
        self.assertEqual(counts["by_kind"]["entity_types"]["pending"], 5)
        self.assertEqual(counts["by_kind"]["relations"]["pending"], 4)

        # Kiểm tra lọc độc lập từng bảng
        t_et = get_edc_table_state(project, "entity_types", state)
        t_rel = get_edc_table_state(project, "relations", state)

        et_filtered = filter_and_sort_proposals(project, "entity_types", t_et["filters"])
        rel_filtered = filter_and_sort_proposals(project, "relations", t_rel["filters"])
        self.assertEqual(len(et_filtered), 5)
        self.assertEqual(len(rel_filtered), 4)
        self.assertTrue(all(p["kind"] == "entity_types" for p in et_filtered))
        self.assertTrue(all(p["kind"] == "relations" for p in rel_filtered))

        # Mở xem chi tiết 1 dòng không tự chọn hay duyệt dòng đó
        set_focused_proposal(project, "entity_types", et_ids[0], state)
        self.assertEqual(t_et["focused_proposal_id"], et_ids[0])
        self.assertEqual(t_et["selected_ids"], [])

        # Chọn trang 1 với page_size=2 -> chỉ chọn 2 mục trên trang 1
        page1, cur_p, total_p = paginate_proposals(et_filtered, page=1, page_size=2)
        self.assertEqual(len(page1), 2)
        self.assertEqual(total_p, 3)
        select_page_proposals(project, "entity_types", page1, state)
        self.assertEqual(len(t_et["selected_ids"]), 2)
        self.assertEqual(t_rel["selected_ids"], [])  # Bảng B không bị ảnh hưởng

        # Đổi trang hoặc đổi thứ tự sắp xếp vẫn giữ nguyên lựa chọn theo ID
        t_et["filters"]["sort_by"] = "alignment_score"
        resorted = filter_and_sort_proposals(project, "entity_types", t_et["filters"])
        page2, _, _ = paginate_proposals(resorted, page=2, page_size=2)
        self.assertEqual(len(t_et["selected_ids"]), 2)

        # Chọn tất cả kết quả lọc -> chọn đủ 5 ID của bảng entity_types
        select_all_filtered_proposals(project, "entity_types", et_filtered, state)
        self.assertEqual(set(t_et["selected_ids"]), set(et_ids))
        self.assertEqual(t_rel["selected_ids"], [])

        # Đổi bộ lọc sang doc_1 (chỉ còn 3 mục) -> tự động loại 2 mục bị ẩn khỏi lựa chọn và có thông báo
        sig1 = compute_filter_signature(t_et["filters"])
        reconcile_selection_with_filter(project, "entity_types", sig1, et_filtered, state)
        t_et["filters"]["doc_id"] = "doc_1"
        sig2 = compute_filter_signature(t_et["filters"])
        et_doc1 = filter_and_sort_proposals(project, "entity_types", t_et["filters"])
        self.assertEqual(len(et_doc1), 3)
        pruned = reconcile_selection_with_filter(project, "entity_types", sig2, et_doc1, state)
        self.assertEqual(pruned, 2)
        self.assertEqual(len(t_et["selected_ids"]), 3)
        self.assertIn("2 mục", t_et["filter_prune_notice"])

        # Bỏ chọn trên bảng A không ảnh hưởng bảng B
        toggle_proposal_selection(project, "relations", rel_ids[0], True, state)
        clear_proposal_selection(project, "entity_types", state)
        self.assertEqual(t_et["selected_ids"], [])
        self.assertEqual(t_rel["selected_ids"], [rel_ids[0]])

        # Đổi dự án xóa toàn bộ lựa chọn, bản nháp và preview cũ
        project_b = _seed_edc_project("Proj_B")
        changed = reset_edc_state_if_project_changed(project_b, state)
        self.assertTrue(changed)
        t_rel_b = get_edc_table_state(project_b, "relations", state)
        self.assertEqual(t_rel_b["selected_ids"], [])

    def test_02_approve_all_uses_distinct_names_and_partial_apply_12_items_with_3_invalid(self) -> None:
        """Kiểm tra:
        - Duyệt toàn bộ dùng tên/định nghĩa riêng từng mục, không gộp vào 1 mục.
        - Với 12 mục có 3 lỗi thiếu định nghĩa: all_or_nothing bị chặn, valid_only chỉ lưu đúng 9 mục hợp lệ và giữ 3 mục lỗi ở pending.
        - Đề xuất thứ 13 xuất hiện sau khi preview không tự động lọt vào lô đã chốt.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facade = KGStudioFacade(
                json_repo=JsonProjectRepository(tmp_path / "projects"),
                sqlite_repo=SQLiteProjectRepository(tmp_path / "test.db"),
                vector_repo=VectorIndexRepository(tmp_path / "vectors"),
            )
            client = FrontendClient(facade=facade)
            project = facade.load_project("Twelve_Items_Project")
            project["extraction_mode"] = MODE_EDC_PLUS_R
            state: dict = {}

            all_12_ids: list[str] = []
            for idx in range(1, 13):
                has_def = idx <= 9
                _, pid = propose_term(
                    project,
                    "entity_types",
                    f"loại di sản {idx}",
                    f"Định nghĩa riêng của loại di sản {idx}" if has_def else "",
                    {"doc_id": "doc_1", "example": f"Mẫu {idx}"},
                )
                all_12_ids.append(pid)
            facade.save_project(project)

            select_all_filtered_proposals(
                project,
                "entity_types",
                [p for p in project["schema_proposals"] if p["kind"] == "entity_types"],
                state,
            )
            preview = build_preview_for_scope(
                project,
                "entity_types",
                all_12_ids,
                batch_action="approve",
                client=client,
                state_store=state,
            )
            self.assertEqual(preview.valid_count, 9)
            self.assertEqual(preview.invalid_count, 3)
            self.assertFalse(preview.can_apply_all)
            self.assertTrue(preview.can_apply_valid_only)
            self.assertEqual(len(preview.locked_proposal_ids), 12)

            # Kiểm tra mỗi mục hợp lệ đều giữ tên chuẩn & định nghĩa riêng
            valid_names = [it["canonical_name"] for it in preview.item_previews if it["valid"]]
            self.assertEqual(len(set(valid_names)), 9)

            # all_or_nothing phải bị từ chối và không lưu bất kỳ mục nào
            with self.assertRaises(ValueError):
                execute_batch_apply(
                    project,
                    "entity_types",
                    apply_mode="all_or_nothing",
                    client=client,
                    state_store=state,
                )
            self.assertEqual(sum(1 for p in project["schema_proposals"] if p["status"] == "approved"), 0)

            # valid_only chỉ lưu đúng 9 mục hợp lệ và giữ lại 3 mục lỗi ở trạng thái pending kèm lựa chọn & bản nháp
            result = execute_batch_apply(
                project,
                "entity_types",
                apply_mode="valid_only",
                client=client,
                state_store=state,
            )
            self.assertEqual(result.status, "committed")
            self.assertEqual(result.applied_count, 9)
            self.assertEqual(result.skipped_count, 3)

            approved_props = [p for p in project["schema_proposals"] if p["status"] == "approved"]
            pending_props = [p for p in project["schema_proposals"] if p["status"] == "pending"]
            self.assertEqual(len(approved_props), 9)
            self.assertEqual(len(pending_props), 3)

            # Danh mục entity_types phải có thêm đúng 9 mục riêng biệt
            cat_names = {r["name"] for r in catalog_rows(project, "entity_types")}
            for idx in range(1, 10):
                self.assertIn(f"loại di sản {idx}", cat_names)
            for idx in range(10, 13):
                self.assertNotIn(f"loại di sản {idx}", cat_names)

            # Sau khi áp dụng: 9 mục thành công đã được bỏ chọn, 3 mục lỗi vẫn được giữ trong selected_ids & drafts
            t_state = get_edc_table_state(project, "entity_types", state)
            self.assertEqual(set(t_state["selected_ids"]), {p["id"] for p in pending_props})
            self.assertEqual(set(t_state["drafts"].keys()), {p["id"] for p in pending_props})
            self.assertIsNotNone(t_state["last_result"])

    def test_03_merge_validations_no_auto_top1_and_validation_rules(self) -> None:
        """Kiểm tra:
        - Hợp nhất nhiều mục vào cùng đích hoặc các đích khác nhau đúng nhóm.
        - Không tự chọn Top-1 để commit nếu người dùng chưa chọn đích.
        - Chặn thiếu định nghĩa, đích đã bị xóa, ID sai dự án, ID trùng có quyết định khác nhau, và nhóm tên mới trùng nhau.
        """
        project = _seed_edc_project("Validation_Project")
        _, r1 = propose_term(project, "relations", "tọa lạc ở", "Nằm tại vị trí", {"doc_id": "d1", "example": "A ở B"})
        _, r2 = propose_term(project, "relations", "nằm ở khu vực", "Thuộc địa phận", {"doc_id": "d1", "example": "C ở D"})
        _, r3 = propose_term(project, "relations", "khởi công năm", "Xây năm", {"doc_id": "d1", "example": "A năm 1049"})
        _, et1 = propose_term(project, "entity_types", "ngôi chùa", "Chùa cổ", {"doc_id": "d1", "example": "Chùa Một Cột"})

        # Giả lập r1 có alignment_candidates Top-1 là "nằm tại"
        for p in project["schema_proposals"]:
            if p["id"] == r1:
                p["alignment_candidates"] = [{"name": "nằm tại", "score": 0.95, "definition": "Vị trí"}]

        # 1. Không tự chọn Top-1 để commit khi tạo bản nháp merge mà chưa chọn đích
        state: dict = {}
        prev_no_target = build_preview_for_scope(
            project,
            "relations",
            [r1],
            batch_action="merge",
            state_store=state,
        )
        self.assertEqual(prev_no_target.invalid_count, 1)
        self.assertIn("Chưa chọn mục đích", prev_no_target.item_previews[0]["errors"][0])

        # 2. Người dùng chủ động bấm "Điền ứng viên đầu tiên vào bản nháp" -> lúc này mới điền vào draft
        fill_info = fill_top1_candidate_to_drafts(project, "relations", [r1, r2], state_store=state)
        self.assertEqual(fill_info["filled_count"], 1)
        self.assertEqual(fill_info["skipped_count"], 1)  # r2 chưa có ứng viên

        # Gán đích cho r2 cùng đích "nằm tại" và r3 vào đích "xây dựng năm"
        assign_shared_target_to_drafts(project, "relations", [r1, r2], "nằm tại", state_store=state)
        prop_r3 = next(p for p in project["schema_proposals"] if p["id"] == r3)
        update_proposal_draft(project, "relations", prop_r3, action="merge", canonical_name="xây dựng năm", state_store=state)

        prev_valid_merge = build_preview_for_scope(
            project,
            "relations",
            [r1, r2, r3],
            batch_action=None,
            state_store=state,
        )
        self.assertEqual(prev_valid_merge.valid_count, 3)
        self.assertTrue(prev_valid_merge.can_apply_all)

        # 3. Kiểm tra chặn: nhóm tên mới trùng nhau (sau chuẩn hóa hoa/thường/khoảng trắng), đích đã xóa, sai nhóm, ID trùng mâu thuẫn, sai project_id
        bad_req = BulkReviewRequestDTO(
            project_id="WRONG_PROJECT_ID",
            kind="relations",
            expected_revision=compute_project_revision(project),
            request_id="req_bad_1",
            decisions=[
                # Hai mục mới trùng tên sau chuẩn hóa -> cả hai đều phải bị đánh dấu lỗi
                ProposalDecisionDTO(proposal_id=r1, kind="relations", action="approve", canonical_name="Quan Hệ Mới", definition="Định nghĩa 1"),
                ProposalDecisionDTO(proposal_id=r2, kind="relations", action="approve", canonical_name="  quan hệ   mới ", definition="Định nghĩa 2"),
                # Hợp nhất vào đích không tồn tại / vừa tạo trong cùng lô
                ProposalDecisionDTO(proposal_id=r3, kind="relations", action="merge", canonical_name="Quan Hệ Mới"),
                # Cùng ID r3 nhưng quyết định mâu thuẫn
                ProposalDecisionDTO(proposal_id=r3, kind="relations", action="reject", note="Mâu thuẫn"),
                # Đề xuất et1 thuộc entity_types đưa nhầm vào lô relations
                ProposalDecisionDTO(proposal_id=et1, kind="entity_types", action="approve", canonical_name="chùa", definition="Định nghĩa"),
            ],
        )
        bad_prev = preview_proposal_decisions(project, bad_req)
        self.assertGreater(len(bad_prev.batch_errors), 0)
        self.assertEqual(bad_prev.valid_count, 0)
        by_pid = {it["proposal_id"]: it for it in bad_prev.item_previews}
        # Cả r1 và r2 đều bị gắn lỗi trùng tên mới trong lô (không mặc định dòng trước thắng)
        self.assertTrue(any("trùng với mục mới khác trong cùng lô" in e for e in by_pid[r1]["errors"]))
        self.assertTrue(any("trùng với mục mới khác trong cùng lô" in e for e in by_pid[r2]["errors"]))
        # r3 bị lỗi cả hợp nhất vào mục mới trong lô lẫn lặp ID mâu thuẫn
        self.assertTrue(any("vừa tạo mới trong cùng lô" in e for e in by_pid[r3]["errors"]))
        self.assertTrue(any("quyết định mâu thuẫn" in e for e in by_pid[r3]["errors"]))
        # et1 bị lỗi sai nhóm
        self.assertTrue(any("không khớp bảng" in e for e in by_pid[et1]["errors"]))

    def test_04_conflict_on_same_node_or_edge_indirect_impact_deduplication_and_edge_gating(self) -> None:
        """Kiểm tra:
        - Chặn quyết định xung đột trên cùng node hoặc cùng cạnh.
        - Đếm ảnh hưởng gián tiếp qua đổi loại node và khử trùng ID cạnh.
        - Duyệt đề xuất không tự duyệt/xuất cạnh; cạnh còn phụ thuộc đề xuất chưa xử lý vẫn bị chặn.
        - Từ chối giữ được đối tượng, bằng chứng và lịch sử; không xóa cứng dữ liệu.
        """
        project = _seed_edc_project("Impact_Conflict_Project")
        _, p_type1 = propose_term(project, "entity_types", "cổ tự", "Chùa cổ", {"doc_id": "d1", "example": "Chùa Một Cột"})
        _, p_type2 = propose_term(project, "entity_types", "danh thắng", "Danh lam", {"doc_id": "d1", "example": "Chùa Một Cột"})
        _, p_type3 = propose_term(project, "entity_types", "quận nội thành", "Quận", {"doc_id": "d1", "example": "Ba Đình"})
        _, p_rel1 = propose_term(project, "relations", "tọa lạc tại", "Nằm ở", {"doc_id": "d1", "example": "Chùa Một Cột -> Ba Đình"})

        # Tạo 2 node và 1 cạnh: node n1 gắn cả p_type1 và p_type2; cạnh e1 nối n1 -> n2 nhưng e1 chỉ lưu p_rel1 trong schema_proposal_ids
        project["nodes"] = [
            {"id": "n1", "name": "Chùa Một Cột", "kind": "cổ tự", "schema_proposal_ids": [p_type1, p_type2]},
            {"id": "n2", "name": "quận Ba Đình", "kind": "quận nội thành", "schema_proposal_ids": [p_type3]},
        ]
        project["edges"] = [
            {
                "id": "e1",
                "source": "n1",
                "target": "n2",
                "relation": "tọa lạc tại",
                "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                "evidence_found": True,
                "doc_id": "d1",
                "status": STATUS_PENDING,
                "extraction_mode": MODE_EDC_PLUS_R,
                "schema_proposal_ids": [p_rel1],
            }
        ]

        # Kiểm tra đếm cạnh gián tiếp qua node n1: p_type1 không nằm trực tiếp trong e1.schema_proposal_ids nhưng vẫn ảnh hưởng gián tiếp tới e1
        imp_t1 = proposal_impact(project, p_type1)
        self.assertEqual(imp_t1["nodes"], ["n1"])
        self.assertEqual(imp_t1["direct_edges"], [])
        self.assertEqual(imp_t1["indirect_edges"], ["e1"])
        self.assertEqual(imp_t1["edges"], ["e1"])

        # Kiểm tra xung đột trên cùng node n1 khi p_type1 và p_type2 gán 2 loại khác nhau
        conflict_req = BulkReviewRequestDTO(
            project_id=project["project_id"],
            kind="entity_types",
            expected_revision=compute_project_revision(project),
            request_id="req_conflict",
            decisions=[
                ProposalDecisionDTO(proposal_id=p_type1, kind="entity_types", action="approve", canonical_name="cổ tự", definition="Định nghĩa 1"),
                ProposalDecisionDTO(proposal_id=p_type2, kind="entity_types", action="approve", canonical_name="danh thắng", definition="Định nghĩa 2"),
            ],
        )
        conflict_prev = preview_proposal_decisions(project, conflict_req)
        self.assertEqual(conflict_prev.valid_count, 0)
        self.assertEqual(conflict_prev.invalid_count, 2)
        for it in conflict_prev.item_previews:
            self.assertTrue(any("Xung đột tác động trên cùng node" in e for e in it["errors"]))

        # Nếu p_type1 và p_type2 cùng merge về 1 đích giống hệt nhau ("di tích"), cùng với p_type3 -> không xung đột và e1 chỉ được đếm 1 lần!
        compat_req = BulkReviewRequestDTO(
            project_id=project["project_id"],
            kind="entity_types",
            expected_revision=compute_project_revision(project),
            request_id="req_compat",
            decisions=[
                ProposalDecisionDTO(proposal_id=p_type1, kind="entity_types", action="merge", canonical_name="di tích"),
                ProposalDecisionDTO(proposal_id=p_type2, kind="entity_types", action="merge", canonical_name="di tích"),
                ProposalDecisionDTO(proposal_id=p_type3, kind="entity_types", action="merge", canonical_name="địa điểm"),
            ],
        )
        compat_prev = preview_proposal_decisions(project, compat_req)
        self.assertEqual(compat_prev.valid_count, 3)
        # Cạnh e1 bị ảnh hưởng bởi cả n1 và n2 nhưng tổng ảnh hưởng chỉ đếm ID duy nhất (1 cạnh)
        self.assertEqual(compat_prev.affected_node_ids, ["n1", "n2"])
        self.assertEqual(compat_prev.affected_edge_ids, ["e1"])

        apply_proposal_decisions(project, compat_req, preview=compat_prev)
        # Duyệt đề xuất danh mục chỉ đưa e1 về Cần kiểm tra, KHÔNG tự duyệt e1
        self.assertEqual(project["edges"][0]["status"], STATUS_CHECK)
        # Vì p_rel1 vẫn đang pending nên e1 vẫn bị chặn không cho duyệt cạnh và không xuất ra đồ thị đã duyệt
        self.assertTrue(bool(schema_review_issue(project, project["edges"][0])))
        with self.assertRaises(ValueError):
            set_edge_status(project, "e1", STATUS_APPROVED)
        nodes_out, edges_out = approved_graph(project)
        self.assertEqual(len(edges_out), 0)

        # Từ chối p_rel1: giữ nguyên đề xuất, nguồn, node, cạnh và chặn tiếp việc duyệt e1
        rej_req = BulkReviewRequestDTO(
            project_id=project["project_id"],
            kind="relations",
            expected_revision=compute_project_revision(project),
            request_id="req_reject_rel",
            decisions=[
                ProposalDecisionDTO(proposal_id=p_rel1, kind="relations", action="reject", note="Quan hệ quá mơ hồ"),
            ],
        )
        apply_proposal_decisions(project, rej_req)
        rel_prop = next(p for p in project["schema_proposals"] if p["id"] == p_rel1)
        self.assertEqual(rel_prop["status"], "rejected")
        self.assertEqual(len(rel_prop["observations"]), 1)
        self.assertEqual(len(project["nodes"]), 2)
        self.assertEqual(len(project["edges"]), 1)
        with self.assertRaises(ValueError):
            set_edge_status(project, "e1", STATUS_APPROVED)

    def test_05_scoped_refresh_candidates_and_staleness_detection(self) -> None:
        """Kiểm tra:
        - Làm mới gợi ý chỉ chạy trên ID đã chọn và không đổi trạng thái quyết định.
        - Khi đổi catalog/định nghĩa/model, gợi ý cũ được đánh dấu stale.
        - Khi thiếu model hoặc lỗi gọi dịch vụ, giữ quyết định cũ và báo lỗi tại dòng.
        """
        with tempfile.TemporaryDirectory() as tmp:
            vec_repo = VectorIndexRepository(Path(tmp) / "vectors")
            embedder = EmbedderGateway("hybrid_vn:default")
            aligner = TargetAligner(vector_repo=vec_repo, embedder=embedder)

            project = _seed_edc_project("Scoped_Refresh")
            _, p1 = propose_term(project, "relations", "tọa lạc ở", "Thực thể nằm tại địa điểm đích", {"doc_id": "d1"})
            _, p2 = propose_term(project, "relations", "khởi dựng năm", "Được xây dựng vào năm đích", {"doc_id": "d1"})

            # Chỉ làm mới gợi ý cho p1, không chạm p2
            summary = aligner.refresh_candidates_for_proposals(
                project,
                proposal_ids=[p1],
                kind="relations",
                candidate_threshold=0.20,
                embedder=embedder,
            )
            self.assertEqual(summary["requested_count"], 1)
            self.assertEqual(summary["refreshed_count"], 1)
            self.assertEqual(summary["error_count"], 0)

            prop1 = next(p for p in project["schema_proposals"] if p["id"] == p1)
            prop2 = next(p for p in project["schema_proposals"] if p["id"] == p2)
            self.assertEqual(prop1["status"], "pending")  # Không tự đổi trạng thái
            self.assertGreater(len(prop1["alignment_candidates"]), 0)
            self.assertEqual(prop2.get("alignment_candidates", []), [])  # p2 không bị chạy ngầm

            # Chưa thay đổi catalog/model -> không bị stale
            stale, _ = is_proposal_candidates_stale(project, prop1, embedder.fingerprint)
            self.assertFalse(stale)

            # Thay đổi model fingerprint hoặc thay đổi định nghĩa -> bị đánh dấu stale
            stale_model, reason_m = is_proposal_candidates_stale(project, prop1, "other_model_fp_999")
            self.assertTrue(stale_model)
            self.assertIn("Mô hình embedding đã thay đổi", reason_m)

            prop1["definition"] = "Định nghĩa mới hoàn toàn khác trước"
            stale_def, reason_d = is_proposal_candidates_stale(project, prop1, embedder.fingerprint)
            self.assertTrue(stale_def)
            self.assertIn("Định nghĩa đề xuất đã thay đổi", reason_d)

            # Giả lập lỗi dịch vụ embedding khi refresh -> giữ nguyên quyết định/trạng thái cũ, ghi lỗi tại dòng
            class _BrokenEmbedder:
                fingerprint = "broken_fp"
                dim = 128

                def encode(self, texts):
                    raise RuntimeError("Mất kết nối dịch vụ Embedding")

            err_summary = aligner.refresh_candidates_for_proposals(
                project,
                proposal_ids=[p1],
                kind="relations",
                embedder=_BrokenEmbedder(),  # type: ignore[arg-type]
            )
            self.assertEqual(err_summary["error_count"], 1)
            self.assertEqual(prop1["status"], "pending")  # Không chuyển thành reject
            self.assertIn("Mất kết nối", prop1["last_refresh_error"])

    def test_06_concurrency_double_click_idempotency_io_rollback_and_sqlite_resync(self) -> None:
        """Kiểm tra:
        - Hai phiên cùng sửa, thay catalog sau preview và nhấn đúp (idempotency) đều có hành vi xác định.
        - Giả lập lỗi giữa các lần ghi JSON khôi phục bộ file cũ.
        - Lỗi SQLite sau commit được báo là chờ đồng bộ (sync_pending) và có thể chạy lại đồng bộ.
        - Khôi phục snapshot đồng bộ lại JSON, SQLite và vô hiệu hóa chỉ mục vector cũ.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facade = KGStudioFacade(
                json_repo=JsonProjectRepository(tmp_path / "projects"),
                sqlite_repo=SQLiteProjectRepository(tmp_path / "test.db"),
                vector_repo=VectorIndexRepository(tmp_path / "vectors"),
            )
            project = _seed_edc_project("Transactional_Project")
            _, p1 = propose_term(project, "entity_types", "tháp cổ", "Công trình dạng tháp", {"doc_id": "d1"})
            _, p2 = propose_term(project, "entity_types", "đình làng", "Ngôi đình cổ", {"doc_id": "d1"})
            facade.save_project(project)

            # Khởi tạo chỉ mục vector trước khi sửa catalog
            embedder = EmbedderGateway("hybrid_vn:default")
            facade.vector_repo.ensure_index(
                project["project_id"],
                "entity_types",
                catalog_rows(project, "entity_types"),
                embedder,
            )
            self.assertTrue(
                facade.vector_repo.get_index_status(
                    project["project_id"],
                    "entity_types",
                    catalog_rows(project, "entity_types"),
                    embedder.fingerprint,
                )["valid"]
            )

            # Hai phiên cùng mở dự án
            session_1 = facade.load_project("Transactional_Project")
            session_2 = facade.load_project("Transactional_Project")

            req_s1 = BulkReviewRequestDTO(
                project_id=session_1["project_id"],
                kind="entity_types",
                expected_revision=facade.project_revision(session_1),
                request_id="req_session_1",
                decisions=[
                    ProposalDecisionDTO(proposal_id=p1, kind="entity_types", action="approve", canonical_name="tháp cổ", definition="Công trình dạng tháp"),
                ],
            )
            req_s2 = BulkReviewRequestDTO(
                project_id=session_2["project_id"],
                kind="entity_types",
                expected_revision=facade.project_revision(session_2),
                request_id="req_session_2",
                decisions=[
                    ProposalDecisionDTO(proposal_id=p2, kind="entity_types", action="approve", canonical_name="đình làng", definition="Ngôi đình cổ"),
                ],
            )

            # Phiên 1 commit thành công
            res_s1 = facade.apply_proposal_decisions(session_1, req_s1)
            self.assertEqual(res_s1.status, "committed")
            self.assertEqual(res_s1.applied_count, 1)
            self.assertEqual(res_s1.vector_index_status, "invalidated")
            self.assertTrue(Path(res_s1.snapshot_path).exists())

            # Nhấn đúp (gửi lại cùng request_id với cùng nội dung) -> trả về kết quả cũ (idempotent_replay=True), không tạo snapshot mới
            snaps_before = len(facade.list_snapshots(session_1))
            res_s1_dup = facade.apply_proposal_decisions(session_1, req_s1)
            self.assertTrue(res_s1_dup.idempotent_replay)
            self.assertEqual(res_s1_dup.batch_id, res_s1.batch_id)
            self.assertEqual(len(facade.list_snapshots(session_1)), snaps_before)

            # Cùng request_id nhưng đổi nội dung quyết định -> bị từ chối
            req_s1_tampered = copy.deepcopy(req_s1)
            req_s1_tampered.decisions[0].canonical_name = "tên khác"
            with self.assertRaises(ValueError):
                facade.apply_proposal_decisions(session_1, req_s1_tampered)

            # Phiên 2 cố commit với expected_revision cũ -> bị chặn không cho ghi đè
            with self.assertRaises(ValueError):
                facade.apply_proposal_decisions(session_2, req_s2)

            # Giả lập lỗi I/O giữa các lần ghi JSON (ghi xong project.json thì lỗi ở entity_types.json) -> rollback toàn bộ bộ file!
            write_calls = 0

            def _flaky_writer(path: Path, data: bytes) -> None:
                nonlocal write_calls
                write_calls += 1
                if write_calls == 2:
                    raise OSError("Giả lập lỗi ổ đĩa khi đang ghi file catalog thứ 2")
                atomic_write(path, data)

            facade.json_repo._writer_fn = _flaky_writer
            req_s2_fresh = BulkReviewRequestDTO(
                project_id=session_1["project_id"],
                kind="entity_types",
                expected_revision=facade.project_revision(session_1),
                request_id="req_io_fail",
                decisions=[
                    ProposalDecisionDTO(proposal_id=p2, kind="entity_types", action="approve", canonical_name="đình làng", definition="Ngôi đình cổ"),
                ],
            )
            with self.assertRaises(OSError):
                facade.apply_proposal_decisions(session_1, req_s2_fresh)

            # Phục hồi writer bình thường và kiểm tra file trên đĩa vẫn nguyên vẹn trạng thái sau lô 1 (p2 vẫn pending)
            facade.json_repo._writer_fn = atomic_write
            reloaded = facade.load_project("Transactional_Project")
            p2_disk = next(p for p in reloaded["schema_proposals"] if p["id"] == p2)
            self.assertEqual(p2_disk["status"], "pending")
            self.assertNotIn("đình làng", {r["name"] for r in catalog_rows(reloaded, "entity_types")})

            # Giả lập lỗi SQLite sau khi JSON đã commit -> vẫn trả về committed kèm sync_pending, và cho phép resync
            orig_sync = facade.sqlite_repo.sync_from_project_dict

            def _broken_sqlite_sync(proj_dict: dict) -> None:
                raise RuntimeError("SQLite database is locked")

            facade.sqlite_repo.sync_from_project_dict = _broken_sqlite_sync  # type: ignore[assignment]
            req_s2_retry = BulkReviewRequestDTO(
                project_id=reloaded["project_id"],
                kind="entity_types",
                expected_revision=facade.project_revision(reloaded),
                request_id="req_sqlite_pending",
                decisions=[
                    ProposalDecisionDTO(proposal_id=p2, kind="entity_types", action="approve", canonical_name="đình làng", definition="Ngôi đình cổ"),
                ],
            )
            res_sqlite_err = facade.apply_proposal_decisions(reloaded, req_s2_retry)
            self.assertEqual(res_sqlite_err.status, "committed")
            self.assertEqual(res_sqlite_err.sync_status, "sync_pending")
            self.assertTrue(reloaded.get("sync_pending"))

            # Khôi phục hàm sync SQLite và gọi resync_sqlite
            facade.sqlite_repo.sync_from_project_dict = orig_sync  # type: ignore[assignment]
            sync_ok = facade.resync_sqlite(reloaded)
            self.assertEqual(sync_ok["status"], "synced")
            self.assertFalse(reloaded.get("sync_pending"))

            # Khôi phục về snapshot trước lô 1 -> cả p1 và p2 đều quay về pending trên cả JSON và SQLite
            facade.restore_snapshot(reloaded, Path(res_s1.snapshot_path))
            statuses = {p["id"]: p["status"] for p in reloaded["schema_proposals"]}
            self.assertEqual(statuses[p1], "pending")
            self.assertEqual(statuses[p2], "pending")

    def test_07_exporter_distinguishes_human_vs_auto_aligned_and_unapproved_evidence(self) -> None:
        """Kiểm tra ActiveLearningExporter không nhầm quyết định tự động, preview hoặc trích dẫn khớp với nhãn con người đã duyệt."""
        with tempfile.TemporaryDirectory() as tmp:
            exporter = ActiveLearningExporter(Path(tmp) / "exports")
            project = _seed_edc_project("Exporter_Audit")

            # Tạo 2 đề xuất quan hệ: 1 mục tự động hợp nhất (auto_aligned=True), 1 mục do con người duyệt
            _, p_auto = propose_term(project, "relations", "nằm ở", "Vị trí", {"doc_id": "d1"})
            _, p_human = propose_term(project, "relations", "khởi dựng năm", "Xây dựng vào năm", {"doc_id": "d1"})
            _, p_rej = propose_term(project, "relations", "liên quan tới", "Quan hệ chung", {"doc_id": "d1"})

            for p in project["schema_proposals"]:
                if p["id"] == p_auto:
                    p.update(status="merged", canonical_name="nằm tại", auto_aligned=True, decision_origin="auto_align")

            decide_proposal(project, p_human, "merge", canonical_name="xây dựng năm", note="Con người xác nhận")
            decide_proposal(project, p_rej, "reject", note="Quá chung chung, không khớp mục nào")

            # Tạo 2 cạnh đều có evidence_found=True, nhưng chỉ cạnh e_approved được con người duyệt (STATUS_APPROVED)
            project["nodes"] = [
                {"id": "n1", "name": "Chùa Một Cột", "kind": "di tích", "schema_proposal_ids": []},
                {"id": "n2", "name": "Ba Đình", "kind": "địa điểm", "schema_proposal_ids": []},
            ]
            project["edges"] = [
                {
                    "id": "e_unapproved",
                    "source": "n1",
                    "target": "n2",
                    "relation": "nằm tại",
                    "evidence": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                    "evidence_found": True,
                    "doc_id": "d1",
                    "chunk_hash": "c1",
                    "status": STATUS_CHECK,
                    "extraction_mode": MODE_EDC_PLUS_R,
                    "schema_proposal_ids": [],
                },
                {
                    "id": "e_approved",
                    "source": "n1",
                    "target": "n2",
                    "relation": "xây dựng năm",
                    "evidence": "Chùa Một Cột được xây dựng năm 1049",
                    "evidence_found": True,
                    "doc_id": "d2",
                    "chunk_hash": "c2",
                    "status": STATUS_APPROVED,
                    "extraction_mode": MODE_EDC_PLUS_R,
                    "schema_proposal_ids": [p_human],
                },
            ]

            canon_pairs = exporter.build_canonicalization_pairs(project)
            # Chỉ xuất đúng p_human; không xuất p_auto (auto_aligned) và không xuất p_rej
            self.assertEqual(len(canon_pairs), 1)
            self.assertEqual(canon_pairs[0].open_name, "khởi dựng năm")

            # Từ chối thông thường không có compared_target không sinh negative pair
            self.assertEqual(len(exporter.build_rejected_negative_pairs(project)), 0)

            # SR triplets và SFT records chỉ lấy cạnh STATUS_APPROVED (e_approved), không lấy e_unapproved dù evidence_found=True
            sr_triplets = exporter.build_sr_triplets(project)
            self.assertEqual(len(sr_triplets), 1)
            self.assertEqual(sr_triplets[0].positive_name, "xây dựng năm")

            sft_records = exporter.build_sft_records(project)
            self.assertEqual(len(sft_records), 1)
            self.assertEqual(sft_records[0].doc_id, "d2")

    def test_08_rest_api_edc_review_endpoints_and_url_project_matching(self) -> None:
        """Kiểm tra các REST endpoint /edc-review/preview, /apply, /refresh-candidates và chặn sai lệch project_id trên URL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facade = KGStudioFacade(
                json_repo=JsonProjectRepository(tmp_path / "projects"),
                sqlite_repo=SQLiteProjectRepository(tmp_path / "test.db"),
                vector_repo=VectorIndexRepository(tmp_path / "vectors"),
            )
            project = _seed_edc_project("API_EDC_Project")
            _, p1 = propose_term(project, "relations", "tọa lạc ở", "Vị trí địa lý", {"doc_id": "d1"})
            facade.save_project(project)

            # 1. Kiểm tra chặn khi project_id trong body khác với tên dự án trên URL
            code_bad, resp_bad = handle_api_request(
                "POST",
                "/api/v1/projects/API_EDC_Project/edc-review/preview",
                {"project_id": "OTHER_PROJ", "kind": "relations", "decisions": []},
                facade=facade,
            )
            self.assertEqual(code_bad, 400)
            self.assertIn("không khớp", resp_bad["error"])

            # 2. Refresh candidates qua API
            code_ref, resp_ref = handle_api_request(
                "POST",
                "/api/v1/projects/API_EDC_Project/edc-review/refresh-candidates",
                {"proposal_ids": [p1], "kind": "relations"},
                facade=facade,
            )
            self.assertEqual(code_ref, 200)
            self.assertEqual(resp_ref["refresh_summary"]["refreshed_count"], 1)

            # 3. Preview và Apply qua API
            loaded = facade.load_project("API_EDC_Project")
            req_body = {
                "project_id": loaded["project_id"],
                "kind": "relations",
                "expected_revision": facade.project_revision(loaded),
                "request_id": "api_req_1",
                "apply_mode": "all_or_nothing",
                "decisions": [
                    {
                        "proposal_id": p1,
                        "kind": "relations",
                        "action": "merge",
                        "canonical_name": "nằm tại",
                    }
                ],
            }
            code_prev, resp_prev = handle_api_request(
                "POST",
                "/api/v1/projects/API_EDC_Project/edc-review/preview",
                req_body,
                facade=facade,
            )
            self.assertEqual(code_prev, 200)
            self.assertEqual(resp_prev["preview"]["valid_count"], 1)

            code_app, resp_app = handle_api_request(
                "POST",
                "/api/v1/projects/API_EDC_Project/edc-review/apply",
                {**req_body, "preview": resp_prev["preview"]},
                facade=facade,
            )
            self.assertEqual(code_app, 200)
            self.assertEqual(resp_app["result"]["applied_count"], 1)


if __name__ == "__main__":
    unittest.main()

