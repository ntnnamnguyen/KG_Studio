"""Application Service cho phân hệ Quản lý Dự án (Projects Module).
Điều phối các nghiệp vụ: Liệt kê, nạp, lưu, tạo bản chụp (snapshot), khôi phục và truy vấn trang dữ liệu qua Ports.
"""
from __future__ import annotations

import threading
from typing import Any

from backend.domain.catalogs.service import compute_project_revision
from backend.modules.projects.application.commit_coordinator import ProjectCommitCoordinator
from backend.modules.projects.ports import ProjectStorePort, ReadProjectionPort


class ProjectsApplicationService:
    def __init__(
        self,
        project_store: ProjectStorePort,
        read_projection: ReadProjectionPort | None = None,
        vector_repo: Any | None = None,
        commit_coordinator: ProjectCommitCoordinator | None = None,
    ) -> None:
        self.project_store = project_store
        self.read_projection = read_projection
        self.vector_repo = vector_repo
        self._last_committed_revision: dict[str, str] = {}
        self.commit_coordinator = commit_coordinator or ProjectCommitCoordinator(
            project_store=self.project_store,
            read_projection=self.read_projection,
            vector_repo=self.vector_repo,
        )

    def get_project_lock(self, project_id: str) -> threading.RLock:
        return self.commit_coordinator.get_project_lock(project_id)

    def list_projects(self) -> list[str]:
        return self.project_store.list_projects()

    def list_project_headers(self) -> list[dict[str, Any]]:
        if hasattr(self.project_store, "list_project_headers"):
            return self.project_store.list_project_headers()
        return [{"name": name} for name in self.list_projects()]

    def load_project(self, name: str) -> dict[str, Any]:
        project = self.project_store.load_project(name)
        proj_id = str(project.get("project_id") or project.get("name") or name)
        self._last_committed_revision[proj_id] = compute_project_revision(project)
        if self.read_projection:
            try:
                self.read_projection.sync_project(project)
                project["sync_pending"] = False
                project["sync_error"] = ""
            except Exception as exc:
                project["sync_pending"] = True
                project["sync_error"] = str(exc)
        return project

    def save_project(self, project: dict[str, Any]) -> Any:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self.get_project_lock(proj_id):
            path = self.project_store.save_project(project)
            self._last_committed_revision[proj_id] = compute_project_revision(project)
            if self.vector_repo:
                try:
                    self.vector_repo.invalidate_project_indices(
                        proj_id,
                        kind="relations",
                        current_catalog_items=project.get("relations", []),
                    )
                    self.vector_repo.invalidate_project_indices(
                        proj_id,
                        kind="entity_types",
                        current_catalog_items=project.get("entity_types", []),
                    )
                except Exception:
                    pass
            if self.read_projection:
                try:
                    self.read_projection.sync_project(project)
                    project["sync_pending"] = False
                    project["sync_error"] = ""
                except Exception as exc:
                    project["sync_pending"] = True
                    project["sync_error"] = str(exc)
            return path

    def create_snapshot(self, project: dict[str, Any], note: str = "", *, copy_from_disk_if_clean: bool = False) -> Any:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self.get_project_lock(proj_id):
            if hasattr(self.project_store, "create_snapshot"):
                try:
                    return self.project_store.create_snapshot(project, copy_from_disk_if_clean=copy_from_disk_if_clean, note=note)
                except TypeError:
                    return self.project_store.create_snapshot(project)
            return None

    def list_snapshots(self, project_or_name: Any) -> list[Any]:
        return self.project_store.list_snapshots(project_or_name)

    def restore_snapshot(self, project_or_name: Any, snapshot_ref: Any) -> dict[str, Any]:
        name = project_or_name if isinstance(project_or_name, str) else str(project_or_name.get("name") or "")
        with self.get_project_lock(name or "default"):
            restored = self.project_store.restore_snapshot(project_or_name, snapshot_ref)
            proj_id = str(restored.get("project_id") or restored.get("name") or name)
            self._last_committed_revision[proj_id] = compute_project_revision(restored)
            if self.vector_repo:
                try:
                    self.vector_repo.invalidate_project_indices(
                        proj_id,
                        kind="relations",
                        current_catalog_items=restored.get("relations", []),
                    )
                    self.vector_repo.invalidate_project_indices(
                        proj_id,
                        kind="entity_types",
                        current_catalog_items=restored.get("entity_types", []),
                    )
                except Exception:
                    pass
            if self.read_projection:
                try:
                    self.read_projection.sync_project(restored)
                    restored["sync_pending"] = False
                    restored["sync_error"] = ""
                except Exception as exc:
                    restored["sync_pending"] = True
                    restored["sync_error"] = str(exc)
            return restored

    def project_revision(self, project: dict[str, Any]) -> str:
        return compute_project_revision(project)

    def resync_sqlite(self, project: dict[str, Any]) -> dict[str, Any]:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self.get_project_lock(proj_id):
            if self.read_projection:
                self.read_projection.sync_project(project)
            if hasattr(self.project_store, "clear_sync_pending"):
                self.project_store.clear_sync_pending(str(project.get("name", "")))
            project["sync_pending"] = False
            project["sync_error"] = ""
            return {"status": "synced", "sync_pending": False, "project_id": proj_id}

    def query_edges_page(self, project_or_id: dict | str, **kwargs) -> Any:
        if not self.read_projection:
            return {"items": [], "total_count": 0, "page": 1, "page_size": 50, "total_pages": 0, "sync_pending": False}
        pid = str(project_or_id.get("project_id", "") if isinstance(project_or_id, dict) else project_or_id)
        res = self.read_projection.query_edges_page(pid, **kwargs)
        if isinstance(project_or_id, dict):
            res["sync_pending"] = bool(project_or_id.get("sync_pending", False))
            res["sync_error"] = str(project_or_id.get("sync_error", ""))
        return res

    def query_nodes_page(self, project_or_id: dict | str, **kwargs) -> Any:
        if not self.read_projection:
            return {"items": [], "total_count": 0, "page": 1, "page_size": 50, "total_pages": 0, "sync_pending": False}
        pid = str(project_or_id.get("project_id", "") if isinstance(project_or_id, dict) else project_or_id)
        res = self.read_projection.query_nodes_page(pid, **kwargs)
        if isinstance(project_or_id, dict):
            res["sync_pending"] = bool(project_or_id.get("sync_pending", False))
            res["sync_error"] = str(project_or_id.get("sync_error", ""))
        return res

    def query_proposals_page(self, project_or_id: dict | str, **kwargs) -> Any:
        if not self.read_projection:
            return {"items": [], "total_count": 0, "page": 1, "page_size": 50, "total_pages": 0, "sync_pending": False}
        pid = str(project_or_id.get("project_id", "") if isinstance(project_or_id, dict) else project_or_id)
        res = self.read_projection.query_proposals_page(pid, **kwargs)
        if isinstance(project_or_id, dict):
            res["sync_pending"] = bool(project_or_id.get("sync_pending", False))
            res["sync_error"] = str(project_or_id.get("sync_error", ""))
        return res

    def get_node_by_id(self, project_or_id: dict | str, node_id: str) -> dict[str, Any] | None:
        if not self.read_projection:
            return None
        pid = str(project_or_id.get("project_id", "") if isinstance(project_or_id, dict) else project_or_id)
        return self.read_projection.get_node_by_id(pid, node_id)

    def get_edge_by_id(self, project_or_id: dict | str, edge_id: str) -> dict[str, Any] | None:
        if not self.read_projection:
            return None
        pid = str(project_or_id.get("project_id", "") if isinstance(project_or_id, dict) else project_or_id)
        return self.read_projection.get_edge_by_id(pid, edge_id)

    def get_project_summary(self, project_or_id: dict | str) -> dict[str, Any]:
        if not self.read_projection or not hasattr(self.read_projection, "get_project_summary"):
            return {}
        summ = self.read_projection.get_project_summary(project_or_id)
        if hasattr(summ, "project_id") and not summ.project_id and isinstance(project_or_id, str):
            proj = self.load_project(project_or_id)
            summ = self.read_projection.get_project_summary(proj)
        return summ.to_dict() if hasattr(summ, "to_dict") else dict(summ)

    def list_project_summaries(self) -> list[dict[str, Any]]:
        names = self.list_projects()
        summaries: list[dict[str, Any]] = []
        for n in names:
            summ_dict = self.get_project_summary(n)
            summaries.append(summ_dict)
        return summaries
