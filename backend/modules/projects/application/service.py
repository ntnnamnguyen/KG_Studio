"""Application Service cho phân hệ Quản lý Dự án (Projects Module).
Điều phối các nghiệp vụ: Liệt kê, nạp, lưu, tạo bản chụp (snapshot), khôi phục và truy vấn trang dữ liệu qua Ports.
"""
from __future__ import annotations

import threading
from typing import Any, Callable
import warnings

from backend.domain.catalogs.service import catalog_rows, compute_project_revision
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
        self.commit_coordinator = commit_coordinator or ProjectCommitCoordinator(
            project_store=self.project_store,
            read_projection=self.read_projection,
            vector_repo=self.vector_repo,
        )
        self._last_committed_revision = self.commit_coordinator._last_committed_revision

    def _resolve_lock_id(self, project_or_name: Any) -> str:
        if isinstance(project_or_name, dict):
            return str(project_or_name.get("project_id") or project_or_name.get("name") or "default")
        name = str(project_or_name or "")
        if name and hasattr(self.project_store, "list_project_headers"):
            try:
                for hdr in self.project_store.list_project_headers():
                    if hdr.get("name") == name and hdr.get("project_id"):
                        return str(hdr["project_id"])
            except Exception:
                pass
        return name or "default"

    def _sync_projection_safe(self, project: dict[str, Any]) -> None:
        if not self.read_projection:
            return
        proj_name = str(project.get("name") or "")
        rev = compute_project_revision(project)
        payload = dict(project, _projection_revision=rev)
        try:
            if hasattr(self.read_projection, "sync_project"):
                self.read_projection.sync_project(payload)
            elif hasattr(self.read_projection, "sync_from_project_dict"):
                self.read_projection.sync_from_project_dict(payload)
            if proj_name and hasattr(self.project_store, "clear_sync_pending"):
                self.project_store.clear_sync_pending(proj_name)
            project["sync_pending"] = False
            project["sync_error"] = ""
        except Exception as exc:
            err_str = str(exc)
            if proj_name and hasattr(self.project_store, "mark_sync_pending"):
                self.project_store.mark_sync_pending(proj_name, err_str)
            project["sync_pending"] = True
            project["sync_error"] = err_str

    def _invalidate_vectors_safe(self, project: dict[str, Any], proj_id: str) -> None:
        if not self.vector_repo:
            return
        for kind in ("relations", "entity_types"):
            try:
                self.vector_repo.invalidate_project_indices(
                    proj_id,
                    kind=kind,
                    current_catalog_items=catalog_rows(project, kind),
                )
            except Exception as exc:
                warnings.warn(
                    f"Không thể vô hiệu hóa vector index ({proj_id}/{kind}): {exc}",
                    RuntimeWarning,
                    stacklevel=2,
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
        self.commit_coordinator.record_committed_state(project)
        self._sync_projection_safe(project)
        return project

    def save_project(self, project: dict[str, Any]) -> Any:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self.get_project_lock(proj_id):
            path = self.project_store.save_project(project)
            self.commit_coordinator.record_committed_state(project)
            self._invalidate_vectors_safe(project, proj_id)
            self._sync_projection_safe(project)
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
        lock_id = self._resolve_lock_id(project_or_name)
        with self.get_project_lock(lock_id):
            restored = self.project_store.restore_snapshot(project_or_name, snapshot_ref)
            proj_id = str(restored.get("project_id") or restored.get("name") or lock_id)
            if proj_id != lock_id:
                with self.get_project_lock(proj_id):
                    self.commit_coordinator.record_committed_state(restored)
                    self._invalidate_vectors_safe(restored, proj_id)
                    self._sync_projection_safe(restored)
            else:
                self.commit_coordinator.record_committed_state(restored)
                self._invalidate_vectors_safe(restored, proj_id)
                self._sync_projection_safe(restored)
            return restored

    def project_revision(self, project: dict[str, Any]) -> str:
        return compute_project_revision(project)

    def resync_sqlite(self, project: dict[str, Any]) -> dict[str, Any]:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        with self.get_project_lock(proj_id):
            if self.read_projection:
                rev = compute_project_revision(project)
                self.read_projection.sync_project(dict(project, _projection_revision=rev))
            if hasattr(self.project_store, "clear_sync_pending"):
                self.project_store.clear_sync_pending(str(project.get("name", "")))
            project["sync_pending"] = False
            project["sync_error"] = ""
            return {"status": "synced", "sync_pending": False, "project_id": proj_id}

    def _query_page_with_freshness(
        self,
        project_or_id: dict | str,
        query_fn: Callable[[str], Any],
    ) -> Any:
        if not self.read_projection:
            return {"items": [], "total_count": 0, "page": 1, "page_size": 50, "total_pages": 0, "sync_pending": False}
        pid = str(project_or_id.get("project_id", "") if isinstance(project_or_id, dict) else project_or_id)
        if isinstance(project_or_id, dict) and not project_or_id.get("sync_pending"):
            if hasattr(self.read_projection, "get_project_revision"):
                db_rev = self.read_projection.get_project_revision(pid)
                cur_rev = compute_project_revision(project_or_id)
                if db_rev != cur_rev:
                    with self.get_project_lock(pid or "default"):
                        self._sync_projection_safe(project_or_id)
        res = query_fn(pid)
        if isinstance(project_or_id, dict):
            res["sync_pending"] = bool(project_or_id.get("sync_pending", False))
            res["sync_error"] = str(project_or_id.get("sync_error", ""))
        return res

    def query_edges_page(self, project_or_id: dict | str, **kwargs) -> Any:
        return self._query_page_with_freshness(
            project_or_id,
            lambda pid: self.read_projection.query_edges_page(pid, **kwargs),
        )

    def query_nodes_page(self, project_or_id: dict | str, **kwargs) -> Any:
        return self._query_page_with_freshness(
            project_or_id,
            lambda pid: self.read_projection.query_nodes_page(pid, **kwargs),
        )

    def query_proposals_page(self, project_or_id: dict | str, **kwargs) -> Any:
        return self._query_page_with_freshness(
            project_or_id,
            lambda pid: self.read_projection.query_proposals_page(pid, **kwargs),
        )

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
            target_name = ""
            if hasattr(self.project_store, "project_exists") and self.project_store.project_exists(project_or_id):
                target_name = project_or_id
            elif hasattr(self.project_store, "list_project_headers"):
                for hdr in self.project_store.list_project_headers():
                    if hdr.get("project_id") == project_or_id or hdr.get("name") == project_or_id:
                        target_name = str(hdr.get("name") or "")
                        break
            if target_name:
                proj = self.load_project(target_name)
                summ = self.read_projection.get_project_summary(proj)
        return summ.to_dict() if hasattr(summ, "to_dict") else dict(summ)

    def list_project_summaries(self) -> list[dict[str, Any]]:
        names = self.list_projects()
        summaries: list[dict[str, Any]] = []
        for n in names:
            summ_dict = self.get_project_summary(n)
            summaries.append(summ_dict)
        return summaries
