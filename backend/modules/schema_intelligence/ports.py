"""Ports cho phân hệ Schema Intelligence (EDC, Catalogs & Target Alignment)."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SchemaVectorIndexPort(Protocol):
    """Port giao tiếp chỉ mục vector danh mục."""

    def invalidate_project_indices(
        self,
        project_name: str,
        kind: str,
        current_catalog_items: list[dict] | None = None,
    ) -> None:
        ...


@runtime_checkable
class SchemaEmbedderPort(Protocol):
    """Port giao tiếp mô hình Embedding cho Schema."""

    @property
    def fingerprint(self) -> str:
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...
