"""Unit tests cho ProjectCommitCoordinator (Gate P3).
Kiểm thử toàn diện 8 bước của transactional commit:
1. Atomicity & Snapshot rollback khi ghi đĩa thất bại.
2. Idempotency replay (trả kết quả cache, không gọi lại executor).
3. Idempotency conflict (từ chối khi trùng request_id nhưng khác payload/hash).
4. Revision conflict (từ chối khi expected_revision bị stale).
5. Đồng bộ SQLite lỗi -> đánh dấu sync_pending an toàn mà không làm hỏng commit JSON.
6. Vô hiệu hóa vector index khi danh mục thay đổi.
"""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import threading
import unittest
from typing import Any

from backend.domain.catalogs.service import compute_project_revision
from backend.modules.projects.application.commit_coordinator import ProjectCommitCoordinator
from shared.schemas.curation import CurationResultDTO
from shared.schemas.edc import BulkReviewResultDTO


class DummyProjectStore:
    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.saved_projects: list[dict[str, Any]] = []
        self.snapshots_created: list[Path] = []
        self.sync_pending_marked: list[tuple[str, str]] = []
        self.fail_save = False

    def find_folder(self, name: str) -> Path | None:
        folder = self.temp_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def load_project(self, name: str) -> dict[str, Any]:
        for p in reversed(self.saved_projects):
            if p.get("name") == name:
                return copy.deepcopy(p)
        return {"name": name, "project_id": "test_pid"}

    def save_project(self, project: dict[str, Any]) -> Any:
        if self.fail_save:
            raise IOError("Simulated disk full / permission error during atomic JSON commit")
        self.saved_projects.append(copy.deepcopy(project))
        folder = self.find_folder(project.get("name", "proj1"))
        p_file = folder / "project.json"
        p_file.write_text("{}", encoding="utf-8")
        return p_file

    def create_snapshot(self, project: dict[str, Any], copy_from_disk_if_clean: bool = False) -> Path:
        snap_file = self.temp_dir / f"snap_{len(self.snapshots_created)}.json"
        snap_file.write_text("{}", encoding="utf-8")
        self.snapshots_created.append(snap_file)
        return snap_file

    def mark_sync_pending(self, proj_name: str, error: str) -> None:
        self.sync_pending_marked.append((proj_name, error))

    def clear_sync_pending(self, proj_name: str) -> None:
        pass


class DummyReadProjection:
    def __init__(self) -> None:
        self.synced_projects: list[dict[str, Any]] = []
        self.fail_sync = False

    def sync_project(self, project: dict[str, Any]) -> None:
        if self.fail_sync:
            raise RuntimeError("Simulated SQLite locked error")
        self.synced_projects.append(copy.deepcopy(project))


class DummyVectorRepo:
    def __init__(self) -> None:
        self.invalidated_calls: list[tuple[str, str]] = []

    def invalidate_project_indices(self, project_id: str, kind: str, current_catalog_items: list[Any]) -> None:
        self.invalidated_calls.append((project_id, kind))


class TestProjectCommitCoordinator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tmp.name)
        self.store = DummyProjectStore(self.temp_path)
        self.projection = DummyReadProjection()
        self.vector_repo = DummyVectorRepo()
        self.coordinator = ProjectCommitCoordinator(
            project_store=self.store,
            read_projection=self.projection,
            vector_repo=self.vector_repo,
        )

        self.project = {
            "project_id": "pid_100",
            "name": "project_alpha",
            "entity_types": ["PERSON"],
            "entity_type_notes": {"PERSON": {"definition": "Con người", "description": ""}},
            "relations": ["TẠI"],
            "relation_notes": {"TẠI": {"definition": "Địa điểm", "description": ""}},
            "nodes": [],
            "edges": [],
        }
        self.store.save_project(self.project)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_successful_commit_flow(self) -> None:
        exec_called = False

        def _executor(proj: dict[str, Any]) -> tuple[dict[str, Any], CurationResultDTO]:
            nonlocal exec_called
            exec_called = True
            c = copy.deepcopy(proj)
            c["nodes"].append({"id": "n1", "name": "Nguyễn Du"})
            res = CurationResultDTO(
                status="committed",
                operation="add_node",
                request_id="req_001",
                revision_after=compute_project_revision(c),
            )
            return c, res

        result = self.coordinator.commit(
            self.project,
            request_id="req_001",
            request_hash="hash_001",
            expected_revision=compute_project_revision(self.project),
            executor=_executor,
            result_dto_cls=CurationResultDTO,
        )

        self.assertTrue(exec_called)
        self.assertEqual(result.status, "committed")
        self.assertEqual(result.sync_status, "synced")
        self.assertTrue(result.snapshot_path)
        self.assertTrue(any(n.get("id") == "n1" for n in self.project["nodes"]))
        self.assertEqual(len(self.projection.synced_projects), 1)

    def test_02_idempotency_replay_and_conflict(self) -> None:
        call_count = 0

        def _executor(proj: dict[str, Any]) -> tuple[dict[str, Any], CurationResultDTO]:
            nonlocal call_count
            call_count += 1
            c = copy.deepcopy(proj)
            res = CurationResultDTO(
                status="committed",
                operation="noop",
                request_id="req_replay",
                revision_after=compute_project_revision(c),
            )
            return c, res

        rev = compute_project_revision(self.project)
        res1 = self.coordinator.commit(
            self.project,
            request_id="req_replay",
            request_hash="hash_identical",
            expected_revision=rev,
            executor=_executor,
            result_dto_cls=CurationResultDTO,
        )
        self.assertEqual(call_count, 1)
        self.assertFalse(getattr(res1, "idempotent_replay", False))

        # Replay with same request_id and same hash
        res2 = self.coordinator.commit(
            self.project,
            request_id="req_replay",
            request_hash="hash_identical",
            expected_revision=rev,
            executor=_executor,
            result_dto_cls=CurationResultDTO,
        )
        self.assertEqual(call_count, 1)  # Executor NOT called again
        self.assertTrue(res2.idempotent_replay)

        # Conflict: same request_id with different hash
        with self.assertRaises(ValueError) as ctx:
            self.coordinator.commit(
                self.project,
                request_id="req_replay",
                request_hash="hash_DIFFERENT",
                expected_revision=rev,
                executor=_executor,
                result_dto_cls=CurationResultDTO,
            )
        self.assertIn("đã được dùng cho một nội dung thao tác khác", str(ctx.exception))

    def test_03_revision_conflict_rejection(self) -> None:
        def _executor(proj: dict[str, Any]) -> tuple[dict[str, Any], CurationResultDTO]:
            c = copy.deepcopy(proj)
            c["nodes"].append({"id": "n2", "name": "Kim Vân Kiều"})
            return c, CurationResultDTO(
                status="committed",
                operation="edit",
                request_id="req_rev_1",
                revision_after=compute_project_revision(c),
            )

        rev_initial = compute_project_revision(self.project)
        self.coordinator.commit(
            self.project,
            request_id="req_rev_1",
            request_hash="h1",
            expected_revision=rev_initial,
            executor=_executor,
            result_dto_cls=CurationResultDTO,
        )

        # A concurrent session attempts commit with the old revision
        with self.assertRaises(ValueError) as ctx:
            self.coordinator.commit(
                self.project,
                request_id="req_rev_2",
                request_hash="h2",
                expected_revision=rev_initial,  # Stale revision!
                executor=_executor,
                result_dto_cls=CurationResultDTO,
            )
        self.assertIn("revision mismatch", str(ctx.exception))

    def test_04_atomic_rollback_on_save_failure(self) -> None:
        self.store.fail_save = True

        def _executor(proj: dict[str, Any]) -> tuple[dict[str, Any], CurationResultDTO]:
            c = copy.deepcopy(proj)
            c["nodes"].append({"id": "corrupted"})
            return c, CurationResultDTO(
                status="committed",
                operation="bad",
                request_id="req_fail",
                revision_after="fake_rev",
            )

        with self.assertRaises(IOError):
            self.coordinator.commit(
                self.project,
                request_id="req_fail",
                request_hash="h_fail",
                expected_revision=compute_project_revision(self.project),
                executor=_executor,
                result_dto_cls=CurationResultDTO,
            )

        # Project in-memory must NOT contain corrupted node
        self.assertFalse(any(n.get("id") == "corrupted" for n in self.project["nodes"]))
        # Snapshot file created before failure must have been cleaned up / unlinked
        self.assertFalse(self.store.snapshots_created[-1].exists())

    def test_05_sqlite_error_marks_sync_pending_safely(self) -> None:
        self.projection.fail_sync = True

        def _executor(proj: dict[str, Any]) -> tuple[dict[str, Any], CurationResultDTO]:
            c = copy.deepcopy(proj)
            c["nodes"].append({"id": "n3", "name": "Thúy Kiều"})
            return c, CurationResultDTO(
                status="committed",
                operation="add_node",
                request_id="req_sql_err",
                revision_after=compute_project_revision(c),
            )

        res = self.coordinator.commit(
            self.project,
            request_id="req_sql_err",
            request_hash="h_sql_err",
            expected_revision=compute_project_revision(self.project),
            executor=_executor,
            result_dto_cls=CurationResultDTO,
        )

        self.assertEqual(res.status, "committed")
        self.assertEqual(res.sync_status, "sync_pending")
        self.assertTrue(self.project["sync_pending"])
        self.assertIn("SQLite locked", self.project["sync_error"])
        self.assertTrue(len(self.store.sync_pending_marked) > 0)

    def test_06_vector_index_invalidation_when_catalog_changes(self) -> None:
        def _executor(proj: dict[str, Any]) -> tuple[dict[str, Any], BulkReviewResultDTO]:
            c = copy.deepcopy(proj)
            c["relations"].append("SINH_TẠI")
            c["relation_notes"]["SINH_TẠI"] = {"definition": "Nơi sinh", "description": ""}
            return c, BulkReviewResultDTO(
                status="committed",
                request_id="req_vec",
                revision_after=compute_project_revision(c),
            )

        res = self.coordinator.commit(
            self.project,
            request_id="req_vec",
            request_hash="h_vec",
            expected_revision=compute_project_revision(self.project),
            executor=_executor,
            result_dto_cls=BulkReviewResultDTO,
            vector_invalidation_kind="relations",
        )

        self.assertEqual(res.status, "committed")
        self.assertEqual(res.vector_index_status, "invalidated")
        self.assertIn(("pid_100", "relations"), self.vector_repo.invalidated_calls)


if __name__ == "__main__":
    unittest.main()
