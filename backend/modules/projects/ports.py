"""Các Ports (Giao diện trừu tượng) cho phân hệ Quản lý Dự án (Projects Module).
Tuân thủ Clean Architecture: Domain/Application định nghĩa Port, Infrastructure implement.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Protocol


class CommitCoordinatorPort(Protocol):
    """Cổng điều phối transaction commit và lock cho dự án."""

    def get_project_lock(self, project_id: str) -> threading.RLock:
        ...

    def record_committed_state(self, project: dict[str, Any], revision: str | None = None) -> str:
        ...

    def save_metadata_in_lock(self, project: dict[str, Any]) -> Any:
        ...

    def commit(
        self,
        project: dict[str, Any],
        *,
        request_id: str,
        request_hash: str,
        expected_revision: str,
        executor: Callable[[dict[str, Any]], tuple[dict[str, Any], Any]],
        idempotency_store_key: str = "curation_idempotency_store",
        result_dto_cls: Any | None = None,
        on_snapshot_created: Callable[[dict[str, Any], Any, str], None] | None = None,
        vector_invalidation_kind: str | tuple[str, ...] | list[str] | None = None,
    ) -> Any:
        ...


class ProjectStorePort(Protocol):
    """Cổng lưu trữ tài liệu dự án Authoritative (JSON Project Store)."""

    def list_projects(self) -> list[str]:
        ...

    def load_project(self, name: str) -> dict[str, Any]:
        ...

    def save_project(self, project: dict[str, Any]) -> Any:
        ...

    def create_snapshot(self, project: dict[str, Any], *, copy_from_disk_if_clean: bool = False, **kwargs: Any) -> Any:
        ...

    def list_snapshots(self, project_or_name: Any) -> list[Any]:
        ...

    def restore_snapshot(self, project_or_name: Any, path_or_id: Any) -> dict[str, Any]:
        ...

    def delete_snapshot(self, path: Any) -> None:
        ...


class ReadProjectionPort(Protocol):
    """Cổng truy vấn đọc nhanh (Read Projection - SQLite SSOT)."""

    def sync_project(self, project: dict[str, Any]) -> None:
        ...

    def query_edges_page(
        self,
        project_id: str,
        status: str = "",
        relation: str = "",
        search: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Any:
        ...

    def query_nodes_page(
        self,
        project_id: str,
        kind: str = "",
        search: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Any:
        ...

    def query_proposals_page(
        self,
        project_id: str,
        kind: str = "",
        status: str = "",
        search: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Any:
        ...

    def get_node_by_id(self, project_id: str, node_id: str) -> dict[str, Any] | None:
        ...

    def get_edge_by_id(self, project_id: str, edge_id: str) -> dict[str, Any] | None:
        ...
