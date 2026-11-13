"""Kiểm thử toàn diện Từ điển bí danh dự án (Dual-Gate Gazetteer) và vòng lặp học phản hồi."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from backend.domain.catalogs.core import compute_project_revision
from backend.domain.curation.gazetteer import (
    clear_gazetteer,
    delete_gazetteer_entry,
    enrich_gazetteer_from_merge,
    gazetteer_to_csv_bytes,
    gazetteer_to_json_bytes,
    list_gazetteer_entries,
    merge_gazetteer_entries,
    parse_gazetteer_bytes,
    preload_gazetteer_template,
    replace_gazetteer_entries,
    upsert_gazetteer_entry,
)
from backend.domain.curation.merge import apply_bulk_entity_merges, apply_entity_merge
from backend.domain.extraction.validator import ensure_node
from backend.facade import get_facade
from backend.modules.curation.application.service import CurationApplicationService
from backend.modules.projects.application.commit_coordinator import ProjectCommitCoordinator
from backend.repositories.json_repo import JsonProjectRepository, empty_project, ensure_project_shape
from shared.schemas.curation import EntityMergeRequestDTO
from shared.text_utils import now_iso


class TestGazetteerFeedbackLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {
            "name": "test_gazetteer_proj",
            "project_id": "test_gazetteer_proj",
            "revision": "rev_001",
            "nodes": [
                {
                    "id": "node_mot_cot",
                    "name": "Chùa Một Cột",
                    "kind": "Di tích",
                    "description": "Ngôi chùa cổ kính ở Hà Nội",
                    "aliases": [],
                    "documents": ["doc1"],
                    "created_at": now_iso(),
                },
                {
                    "id": "node_dien_huu",
                    "name": "Diên Hựu Tự",
                    "kind": "Di tích",
                    "description": "Tên chữ của Chùa Một Cột",
                    "aliases": ["Chùa Mật"],
                    "documents": ["doc2"],
                    "created_at": now_iso(),
                },
            ],
            "edges": [],
            "entity_types": [{"name": "Di tích"}],
            "relations": [],
            "domain_gazetteer": {},
        }

    def test_enrich_gazetteer_from_merge(self) -> None:
        """Kiểm thử hàm enrich_gazetteer_from_merge tự động tạo ánh xạ khi gộp."""
        absorbed = [self.project["nodes"][1]]
        added = enrich_gazetteer_from_merge(
            self.project,
            canonical_name="Chùa Một Cột",
            canonical_kind="Di tích",
            absorbed_nodes=absorbed,
            merge_id="mrg_001",
            actor="curator_test",
        )

        self.assertIn("diên hựu tự", added)
        self.assertIn("chùa mật", added)
        self.assertEqual(added["diên hựu tự"]["canonical_name"], "Chùa Một Cột")
        self.assertEqual(added["chùa mật"]["canonical_name"], "Chùa Một Cột")
        self.assertEqual(added["diên hựu tự"]["source"], "human_curation_merge")

    def test_ensure_node_with_gazetteer_resolution(self) -> None:
        """Kiểm thử ensure_node tra cứu O(1) từ điển để tự động liên kết về node chuẩn."""
        self.project["domain_gazetteer"]["diên hựu tự"] = {
            "canonical_name": "Chùa Một Cột",
            "kind": "Di tích",
            "source": "manual",
        }

        node_id = ensure_node(
            self.project,
            name="Diên Hựu Tự",
            kind="Di tích",
            description="Thông tin thêm",
            doc_id="doc_new",
        )

        self.assertEqual(node_id, "node_mot_cot")
        target_node = next(n for n in self.project["nodes"] if n["id"] == "node_mot_cot")
        self.assertIn("Diên Hựu Tự", target_node["aliases"])
        self.assertIn("doc_new", target_node["documents"])

    def test_ensure_node_creates_canonical_node_if_not_exists(self) -> None:
        """Nếu node chuẩn chưa tồn tại trong nodes, ensure_node tạo node theo tên chuẩn và lưu alias ban đầu."""
        self.project["domain_gazetteer"]["trấn vũ quán"] = {
            "canonical_name": "Đền Quán Thánh",
            "kind": "Di tích",
            "source": "manual",
        }

        node_id = ensure_node(
            self.project,
            name="Trấn Vũ Quán",
            kind="Di tích",
            description="Ngôi đền trấn bắc Thăng Long",
            doc_id="doc_tran_vu",
        )

        new_node = next(n for n in self.project["nodes"] if n["id"] == node_id)
        self.assertEqual(new_node["name"], "Đền Quán Thánh")
        self.assertIn("Trấn Vũ Quán", new_node["aliases"])

    def test_ensure_node_kind_conflict_blocks_false_polysemy_link(self) -> None:
        """Từ điển có ghi loại cụ thể khác loại đang trích xuất thì không ép gộp nhầm (chống đa nghĩa)."""
        self.project["domain_gazetteer"]["bình đà"] = {
            "canonical_name": "Làng Bình Đà",
            "kind": "Địa danh",
            "source": "manual",
        }

        node_id = ensure_node(
            self.project,
            name="Bình Đà",
            kind="Sản phẩm",
            doc_id="doc_phap",
            strict_kind=True,
        )
        new_node = next(n for n in self.project["nodes"] if n["id"] == node_id)
        self.assertEqual(new_node["name"], "Bình Đà")
        self.assertEqual(new_node["kind"], "Sản phẩm")

    def test_apply_entity_merge_triggers_gazetteer_feedback_loop(self) -> None:
        """Kiểm thử tích hợp: Gộp thực thể ở Bước 4 tự động làm giàu từ điển và giải quyết nạp ở Bước 1."""
        req = EntityMergeRequestDTO(
            project_id="test_gazetteer_proj",
            member_ids=["node_mot_cot", "node_dien_huu"],
            keep_id="node_mot_cot",
            canonical_name="Chùa Một Cột",
            canonical_kind="Di tích",
            canonical_description="Mô tả chuẩn sau gộp",
            actor="test_user",
        )

        candidate, result = apply_entity_merge(self.project, req, mutate_in_place=False)
        self.assertIn(result.status, ("committed", "applied"))

        gaz = candidate.get("domain_gazetteer", {})
        self.assertIn("diên hựu tự", gaz)
        self.assertIn("chùa mật", gaz)
        self.assertEqual(gaz["diên hựu tự"]["canonical_name"], "Chùa Một Cột")

        resolved_id = ensure_node(
            candidate,
            name="Diên Hựu Tự",
            kind="Di tích",
            doc_id="doc_future",
        )
        self.assertEqual(resolved_id, "node_mot_cot")

    def test_parse_gazetteer_bytes_json_and_csv_formats(self) -> None:
        """Kiểm thử phân tích đa định dạng JSON & CSV tải lên ở Bước 2."""
        # 1. Flat JSON dict
        flat_json = json.dumps({"Bác": "Hồ Chí Minh", "same": "SAME", "bad": ""}, ensure_ascii=False).encode("utf-8")
        rows_flat = parse_gazetteer_bytes(flat_json, "flat.json")
        self.assertEqual(len(rows_flat), 1)
        self.assertEqual(rows_flat[0]["alias"], "Bác")
        self.assertEqual(rows_flat[0]["canonical_name"], "Hồ Chí Minh")

        # 2. List JSON with alternative keys
        list_json = json.dumps(
            [{"from": "Hồ Gươm", "to": "Hồ Hoàn Kiếm", "kind": "Địa danh"}],
            ensure_ascii=False,
        ).encode("utf-8")
        rows_list = parse_gazetteer_bytes(list_json, "list.json")
        self.assertEqual(rows_list[0]["canonical_name"], "Hồ Hoàn Kiếm")
        self.assertEqual(rows_list[0]["kind"], "Địa danh")

        # 3. CSV with BOM & Vietnamese header
        csv_header = "bí danh,tên chuẩn,loại\nViện BTTLH,Bảo tàng Dân tộc học Việt Nam,Địa điểm\n".encode("utf-8-sig")
        rows_csv = parse_gazetteer_bytes(csv_header, "dict.csv")
        self.assertEqual(len(rows_csv), 1)
        self.assertEqual(rows_csv[0]["alias"], "Viện BTTLH")
        self.assertEqual(rows_csv[0]["canonical_name"], "Bảo tàng Dân tộc học Việt Nam")
        self.assertEqual(rows_csv[0]["kind"], "Địa điểm")

        # 4. CSV without header
        csv_no_header = "Trấn Vũ Quán,Đền Quán Thánh,Di tích\n".encode("utf-8")
        rows_pos = parse_gazetteer_bytes(csv_no_header, "raw.csv")
        self.assertEqual(rows_pos[0]["alias"], "Trấn Vũ Quán")
        self.assertEqual(rows_pos[0]["canonical_name"], "Đền Quán Thánh")

    def test_export_roundtrip_replace_merge_and_clear(self) -> None:
        """Kiểm thử xuất JSON/CSV round-trip, replace bảo toàn provenance, merge và clear."""
        upsert_gazetteer_entry(
            self.project,
            alias="Diên Hựu Tự",
            canonical_name="Chùa Một Cột",
            kind="Di tích",
            source="human_curation_merge",
        )

        # Replace giữ nguyên dòng cũ -> phải bảo toàn source='human_curation_merge'
        entries_for_edit = list_gazetteer_entries(self.project) + [
            {"alias": "Bác", "canonical_name": "Hồ Chí Minh", "kind": "Nhân vật"}
        ]
        count = replace_gazetteer_entries(self.project, entries_for_edit, source="manual_editor")
        self.assertEqual(count, 2)
        self.assertEqual(self.project["domain_gazetteer"]["diên hựu tự"]["source"], "human_curation_merge")
        self.assertEqual(self.project["domain_gazetteer"]["bác"]["source"], "manual_editor")

        # Merge không ghi đè mục cũ
        merge_summary = merge_gazetteer_entries(
            self.project,
            [
                {"alias": "Bác", "canonical_name": "Bác Hồ", "kind": "Nhân vật"},
                {"alias": "Hồ Gươm", "canonical_name": "Hồ Hoàn Kiếm", "kind": "Địa danh"},
            ],
            source="imported_file",
            overwrite_existing=False,
        )
        self.assertEqual(merge_summary["added"], 1)
        self.assertEqual(merge_summary["skipped"], 1)
        self.assertEqual(self.project["domain_gazetteer"]["bác"]["canonical_name"], "Hồ Chí Minh")

        # Round-trip JSON & CSV export -> parse
        j_bytes = gazetteer_to_json_bytes(self.project)
        c_bytes = gazetteer_to_csv_bytes(self.project)
        self.assertEqual(len(parse_gazetteer_bytes(j_bytes, "export.json")), 3)
        self.assertEqual(len(parse_gazetteer_bytes(c_bytes, "export.csv")), 3)

        # Clear & delete
        self.assertTrue(delete_gazetteer_entry(self.project, "Bác"))
        cleared = clear_gazetteer(self.project)
        self.assertEqual(cleared, 2)
        self.assertEqual(self.project["domain_gazetteer"], {})

    def test_revision_tracks_gazetteer_and_project_shape(self) -> None:
        """Kiểm thử compute_project_revision và empty_project/ensure_project_shape."""
        proj = empty_project("gaz_shape_test")
        self.assertEqual(proj["domain_gazetteer"], {})
        rev1 = compute_project_revision(proj)

        upsert_gazetteer_entry(proj, alias="Văn Miếu", canonical_name="Văn Miếu - Quốc Tử Giám", kind="Di tích")
        rev2 = compute_project_revision(proj)
        self.assertNotEqual(rev1, rev2)

        legacy_proj = {"name": "legacy_no_gaz"}
        shaped = ensure_project_shape(legacy_proj)
        self.assertEqual(shaped["domain_gazetteer"], {})

    def test_preload_historical_template(self) -> None:
        """Kiểm thử nạp bộ từ điển di tích lịch sử Hà Nội mẫu."""
        template_path = Path("data/hanoi_historical_gazetteer.json")
        self.assertTrue(template_path.exists())

        with open(template_path, "r", encoding="utf-8") as f:
            template_data = json.load(f)

        count = preload_gazetteer_template(self.project, template_data)
        self.assertGreaterEqual(count, 20)
        gaz = self.project["domain_gazetteer"]
        self.assertIn("diên hựu tự", gaz)
        self.assertIn("trấn vũ quán", gaz)
        self.assertIn("hồ gươm", gaz)
        self.assertEqual(gaz["hồ gươm"]["canonical_name"], "Hồ Hoàn Kiếm")

    def test_commit_coordinator_transactional_gazetteer_ops(self) -> None:
        """Kiểm thử giao dịch qua ProjectCommitCoordinator: snapshot BEFORE mutation, lock, revision & idempotency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = JsonProjectRepository(Path(tmpdir))
            proj = empty_project("gaz_tx_test")
            repo.save_project(proj)

            coordinator = ProjectCommitCoordinator(project_store=repo)
            svc = CurationApplicationService(commit_coordinator=coordinator, project_store=repo)

            # 1. Nạp trước qua merge_gazetteer_entries
            rev0 = compute_project_revision(proj)
            res1 = svc.merge_gazetteer_entries(
                proj,
                [{"alias": "Diên Hựu Tự", "canonical_name": "Chùa Một Cột", "kind": "Di tích"}],
                expected_revision=rev0,
                request_id="req_gaz_1",
            )
            self.assertEqual(res1.status, "applied")
            self.assertNotEqual(res1.revision_before, res1.revision_after)
            self.assertTrue(Path(res1.snapshot_path).exists())

            # Snapshot được chụp TRƯỚC mutation nên trong snapshot phải chưa có "diên hựu tự"
            snap_data = json.loads(Path(res1.snapshot_path).read_text(encoding="utf-8"))
            self.assertEqual(snap_data.get("domain_gazetteer", {}), {})

            # File project.json trên đĩa đã được lưu đầy đủ
            disk_proj = repo.load_project("gaz_tx_test")
            self.assertIn("diên hựu tự", disk_proj["domain_gazetteer"])

            # 2. Kiểm tra Idempotent Replay
            res_replay = svc.merge_gazetteer_entries(
                proj,
                [{"alias": "Diên Hựu Tự", "canonical_name": "Chùa Một Cột", "kind": "Di tích"}],
                expected_revision=rev0,
                request_id="req_gaz_1",
            )
            self.assertTrue(res_replay.idempotent_replay)

            # 3. Kiểm tra optimistic revision conflict bị chặn đứng
            with self.assertRaises(ValueError):
                svc.upsert_gazetteer_entry(
                    proj,
                    alias="Bác",
                    canonical_name="Hồ Chí Minh",
                    expected_revision="stale_rev_wrong",
                )

            # 4. Xóa entry và xóa sạch qua Coordinator
            rev_curr = compute_project_revision(proj)
            res_del = svc.delete_gazetteer_entry(proj, "Diên Hựu Tự", expected_revision=rev_curr)
            self.assertEqual(res_del.applied_count, 1)
            self.assertEqual(repo.load_project("gaz_tx_test")["domain_gazetteer"], {})

    def test_bulk_entity_merge_and_notice_formatting(self) -> None:
        """Kiểm thử gộp hàng loạt (Bulk Merge) tự động làm giàu từ điển và sinh thông báo UI."""
        from frontend.components.merge.entity_tab import _format_gazetteer_merge_notice

        cand, res = apply_bulk_entity_merges(
            self.project,
            [("node_mot_cot", "node_dien_huu")],
            actor="bulk_tester",
            mutate_in_place=False,
        )
        self.assertEqual(res.status, "applied")
        self.assertIn("chùa một cột", cand["domain_gazetteer"])
        self.assertEqual(cand["domain_gazetteer"]["chùa một cột"]["canonical_name"], "Diên Hựu Tự")

        notice = _format_gazetteer_merge_notice(cand)
        self.assertIn("Đã thêm", notice)
        self.assertIn("Từ điển Dự án", notice)
        self.assertIn("Chùa Một Cột", notice)

    def test_facade_and_ui_modules_import_cleanly(self) -> None:
        """Kiểm thử Facade ủy quyền và các trang giao diện Bước 2 / Bước 4 import sạch."""
        import frontend.components.gazetteer_panel  # noqa: F401
        import frontend.pages.p02_catalogs_prompts  # noqa: F401
        import frontend.pages.p04_curation_hub  # noqa: F401

        facade = get_facade()
        entries = facade.list_gazetteer_entries(self.project)
        self.assertIsInstance(entries, list)
        parsed = facade.parse_gazetteer_bytes(b"a,b,k\n", "x.csv")
        self.assertEqual(parsed, [{"alias": "a", "canonical_name": "b", "kind": "k"}])


if __name__ == "__main__":
    unittest.main()
