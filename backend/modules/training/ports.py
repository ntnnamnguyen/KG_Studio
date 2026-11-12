"""Ports cho phân hệ Training & ML Lab Integration."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TrainingDatasetExporterPort(Protocol):
    """Port xuất dữ liệu Active Learning từ các quyết định kiểm duyệt."""

    def export_project(self, project: dict) -> dict[str, Any]:
        ...
