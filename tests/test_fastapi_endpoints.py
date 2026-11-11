"""Kiểm thử tự động cho toàn bộ hệ thống FastAPI REST Endpoints & Pydantic v2."""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.main import app
from shared.schemas.curation import CurationReviewRequestDTO, EdgeReviewDecisionDTO
from shared.schemas.edc import BulkReviewRequestDTO


class TestFastAPIEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        from backend.facade import get_facade
        facade = get_facade()
        projects = facade.list_projects()
        cls.project_name = "HaNoiQA6" if "HaNoiQA6" in projects else (projects[0] if projects else "HanoiQA")
        proj = facade.load_project(cls.project_name) if projects else {}
        cls.project_id = str(proj.get("project_id", "7044baf1193541"))

    def test_health_endpoint(self) -> None:
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("modes", data)
        self.assertGreaterEqual(len(data["modes"]), 1)

    def test_models_endpoint(self) -> None:
        resp = self.client.get("/api/v1/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("models", data)
        self.assertIsInstance(data["models"], list)

    def test_projects_list_and_detail(self) -> None:
        resp = self.client.get("/api/v1/projects")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("projects", data)
        self.assertGreaterEqual(len(data["projects"]), 1)

        # Existing project must load successfully
        resp_hanoi = self.client.get(f"/api/v1/projects/{self.project_name}")
        self.assertEqual(resp_hanoi.status_code, 200)
        proj_data = resp_hanoi.json()
        self.assertIn("project", proj_data)
        self.assertEqual(proj_data["project"]["project_id"], self.project_id)

    def test_project_not_found(self) -> None:
        resp = self.client.get("/api/v1/projects/NonExistentProject_9999")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("không tồn tại", resp.json()["detail"])

    def test_openapi_schema_generation(self) -> None:
        resp = self.client.get("/openapi.json")
        self.assertEqual(resp.status_code, 200)
        schema = resp.json()
        self.assertEqual(schema["info"]["title"], "KG Studio Pro Commercial & ML API")
        self.assertEqual(schema["info"]["version"], "2.0.0")
        self.assertIn("/api/v1/health", schema["paths"])
        self.assertIn("/api/v1/projects", schema["paths"])
        self.assertIn("/api/v1/projects/{project_name}/curation/preview-edges", schema["paths"])
        self.assertIn("/api/v1/projects/{project_name}/edc/preview", schema["paths"])
        self.assertIn("/api/v1/projects/{project_name}/graph/retrieve-subgraph", schema["paths"])

    def test_schema_retrieval_endpoint(self) -> None:
        resp = self.client.post(
            f"/api/v1/projects/{self.project_name}/retrieve-schema",
            json={"chunk_text": "Chùa Một Cột được xây dựng từ thời nhà Lý."},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("retrieved", data)
        self.assertIn("relations", data["retrieved"])
        self.assertIn("entity_types", data["retrieved"])

    def test_target_alignment_endpoint(self) -> None:
        resp = self.client.post(
            f"/api/v1/projects/{self.project_name}/align-target",
            json={
                "kind": "relations",
                "name": "nằm tại địa chỉ",
                "definition": "Chỉ vị trí địa lý của địa danh hoặc công trình",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("candidates", data)
        self.assertIsInstance(data["candidates"], list)

    def test_curation_preview_endpoint_with_pydantic(self) -> None:
        dto = CurationReviewRequestDTO(
            project_id=self.project_id,
            decisions=[
                EdgeReviewDecisionDTO(
                    edge_id="fake_edge_001",
                    action="approved",
                    note="Duyệt dữ kiện qua FastAPI",
                )
            ],
        )
        resp = self.client.post(
            f"/api/v1/projects/{self.project_name}/curation/preview-edges",
            json=dto.to_dict(),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("preview", data)
        self.assertEqual(data["preview"]["project_id"], self.project_id)

    def test_edc_preview_endpoint_with_pydantic(self) -> None:
        dto = BulkReviewRequestDTO(
            project_id=self.project_id,
            decisions=[],
        )
        resp = self.client.post(
            f"/api/v1/projects/{self.project_name}/edc/preview",
            json=dto.to_dict(),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("preview", data)


if __name__ == "__main__":
    unittest.main()
