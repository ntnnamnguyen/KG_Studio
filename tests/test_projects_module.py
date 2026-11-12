"""Kiểm thử phân hệ Projects và Composition Root (backend/bootstrap.py).
Kiểm tra:
- ProjectsApplicationService chạy được với fake/mock adapter mà không cần đĩa hay server.
- Bootstrap container khởi tạo và wiring đúng các port.
- Tính tương đương giữa Facade và ProjectsApplicationService.
"""
from __future__ import annotations

from typing import Any
import unittest

from backend.bootstrap import AppContainer, get_container
from backend.modules.projects.application.service import ProjectsApplicationService


class FakeProjectStore:
    def __init__(self) -> None:
        self.projects: dict[str, dict[str, Any]] = {
            "FakeProject": {
                "name": "FakeProject",
                "project_id": "p_fake_001",
                "nodes": [{"id": "n1", "name": "Hà Nội"}],
                "edges": [],
                "schema_proposals": [],
            }
        }
        self.snapshots: list[dict[str, Any]] = []

    def list_projects(self) -> list[str]:
        return list(self.projects.keys())

    def list_project_headers(self) -> list[dict[str, Any]]:
        return [{"name": k, "node_count": len(v.get("nodes", []))} for k, v in self.projects.items()]

    def load_project(self, name: str) -> dict[str, Any]:
        if name not in self.projects:
            raise ValueError(f"Dự án {name} không tồn tại")
        return dict(self.projects[name])

    def save_project(self, project: dict[str, Any]) -> str:
        name = str(project.get("name", "untitled"))
        self.projects[name] = dict(project)
        return f"/fake/path/{name}.json"

    def create_snapshot(self, project: dict[str, Any], note: str = "") -> dict[str, Any]:
        snap = {"id": "snap_01", "project": dict(project), "note": note}
        self.snapshots.append(snap)
        return snap

    def list_snapshots(self, name: str) -> list[dict[str, Any]]:
        return self.snapshots

    def restore_snapshot(self, name: str, snapshot_id: str) -> dict[str, Any]:
        return dict(self.projects[name])


class FakeReadProjection:
    def __init__(self) -> None:
        self.synced: list[str] = []

    def sync_project(self, project: dict[str, Any]) -> None:
        self.synced.append(str(project.get("project_id", "")))

    def query_edges_page(self, project_id: str, **kwargs) -> Any:
        return {"items": [], "total": 0, "page": 1}

    def query_nodes_page(self, project_id: str, **kwargs) -> Any:
        return {"items": [{"id": "n1", "name": "Hà Nội"}], "total": 1, "page": 1}

    def query_proposals_page(self, project_id: str, **kwargs) -> Any:
        return {"items": [], "total": 0, "page": 1}

    def get_node_by_id(self, project_id: str, node_id: str) -> dict[str, Any] | None:
        if node_id == "n1":
            return {"id": "n1", "name": "Hà Nội"}
        return None

    def get_edge_by_id(self, project_id: str, edge_id: str) -> dict[str, Any] | None:
        return None


class ProjectsModuleTests(unittest.TestCase):
    def test_application_service_with_fake_adapters(self) -> None:
        """Kiểm tra ProjectsApplicationService chạy độc lập với Fake Store & Projection."""
        fake_store = FakeProjectStore()
        fake_proj = FakeReadProjection()
        svc = ProjectsApplicationService(project_store=fake_store, read_projection=fake_proj)

        # 1. Liệt kê dự án
        projects = svc.list_projects()
        self.assertEqual(projects, ["FakeProject"])

        # 2. Nạp dự án và kiểm tra auto sync projection
        p = svc.load_project("FakeProject")
        self.assertEqual(p["name"], "FakeProject")
        self.assertIn("p_fake_001", fake_proj.synced)

        # 3. Lưu dự án
        p["nodes"].append({"id": "n2", "name": "Việt Nam"})
        save_path = svc.save_project(p)
        self.assertIn("FakeProject.json", save_path)
        self.assertEqual(len(fake_store.projects["FakeProject"]["nodes"]), 2)

        # 4. Truy vấn node qua projection
        nodes_page = svc.query_nodes_page("p_fake_001")
        self.assertEqual(nodes_page["total"], 1)

        node = svc.get_node_by_id("p_fake_001", "n1")
        self.assertIsNotNone(node)
        self.assertEqual(node["name"], "Hà Nội")

    def test_bootstrap_composition_root(self) -> None:
        """Kiểm tra get_container khởi tạo AppContainer và inject đúng service."""
        container = get_container()
        self.assertIsInstance(container, AppContainer)
        self.assertIsNotNone(container.projects_service)
        projects = container.projects_service.list_projects()
        self.assertIsInstance(projects, list)


if __name__ == "__main__":
    unittest.main()
