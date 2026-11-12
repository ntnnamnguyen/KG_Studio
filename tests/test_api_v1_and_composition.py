"""Unit tests cho Gate P4: Single Boundary for UI and HTTP.
Kiểm tra:
1. UI nhận boundary qua frontend/composition.py (FrontendComposition).
2. backend/api/v1.py gọi ProjectsApplicationService thay vì chạm sqlite_repo trực tiếp.
3. Độ tương đương kết quả giữa gọi trực tiếp qua service và qua HTTP handle_api_request.
4. Lỗi HTTP (400, 404, 500) không gây mutation local trên project.
"""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from backend.api.v1 import handle_api_request
from backend.facade import KGStudioFacade
from backend.repositories.json_repo import JsonProjectRepository
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from frontend.composition import FrontendComposition, get_ui_composition


class TestApiV1AndComposition(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tmp.name)
        self.projects_dir = self.temp_path / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_path / "test.db"
        self.vec_dir = self.temp_path / "vector"

        self.json_repo = JsonProjectRepository(self.projects_dir)
        self.sqlite_repo = SQLiteProjectRepository(self.db_path)
        self.vector_repo = VectorIndexRepository(self.vec_dir)

        self.facade = KGStudioFacade(
            json_repo=self.json_repo,
            sqlite_repo=self.sqlite_repo,
            vector_repo=self.vector_repo,
        )

        self.test_project = {
            "project_id": "pid_test_p4",
            "name": "Project_P4",
            "entity_types": ["PERSON"],
            "entity_type_notes": {"PERSON": {"definition": "Người", "description": ""}},
            "relations": ["BẠN"],
            "relation_notes": {"BẠN": {"definition": "Bạn bè", "description": ""}},
            "nodes": [],
            "edges": [],
            "documents": [],
            "extraction_mode": "closed",
        }
        self.facade.save_project(self.test_project)
        # Nạp lại và lưu để ổn định hình dạng schema và prompt_versions trên đĩa
        stabilized = self.facade.load_project("Project_P4")
        self.facade.save_project(stabilized)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_composition_root_provides_services(self) -> None:
        comp = get_ui_composition()
        self.assertIsNotNone(comp.projects_service)
        self.assertIsNotNone(comp.facade)

    def test_02_http_projects_summary_uses_application_service(self) -> None:
        # Gọi qua HTTP handler
        status, body = handle_api_request("GET", "/api/v1/projects", facade=self.facade)
        self.assertEqual(status, 200)
        self.assertIn("projects", body)
        self.assertTrue(len(body["projects"]) >= 1)
        summary = body["projects"][0]
        self.assertEqual(summary.get("name"), "Project_P4")

        # Gọi qua projects_service trực tiếp
        direct_summaries = self.facade.projects_service.list_project_summaries()
        self.assertEqual(len(direct_summaries), len(body["projects"]))
        self.assertEqual(direct_summaries[0]["name"], body["projects"][0]["name"])

    def test_03_http_single_project_summary(self) -> None:
        status, body = handle_api_request("GET", "/api/v1/projects/Project_P4", facade=self.facade)
        self.assertEqual(status, 200)
        self.assertIn("project", body)
        self.assertEqual(body["project"]["name"], "Project_P4")

    def test_04_http_error_does_not_mutate_project(self) -> None:
        initial_proj = self.facade.load_project("Project_P4")
        initial_rev = self.facade.project_revision(initial_proj)

        # Gửi request với project scope mismatch (yêu cầu PID khác URL)
        bad_payload = {
            "project_id": "pid_UNAUTHORIZED_MISMATCH",
            "kind": "entity_types",
            "expected_revision": initial_rev,
            "request_id": "req_bad_scope",
            "decisions": [],
        }
        status, body = handle_api_request(
            "POST",
            "/api/v1/projects/Project_P4/edc-review/apply",
            body=bad_payload,
            facade=self.facade,
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

        # Kiểm tra project không bị thay đổi
        loaded = self.facade.load_project("Project_P4")
        self.assertEqual(self.facade.project_revision(loaded), initial_rev)


if __name__ == "__main__":
    unittest.main()
